"""Anthropic Claude API backend (pay-per-use API key).

One streamed Messages API conversation: the drawing digest sits in a cached system block (follow-up
questions on the same drawing reuse it), the model may call the read-only lookup tools, and the final
answer is constrained to the plan JSON schema (`output_config.format`). Adaptive thinking with
summarized display feeds the progress view.

Credentials: ANTHROPIC_API_KEY (or ANTHROPIC_AUTH_TOKEN / an `ant auth login` profile).
Model: DWG_TAKEOFF_ANTHROPIC_MODEL (default claude-opus-5-5).
Server-side refusal fallback (`fallbacks: "default"`) is enabled.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .. import config
from .prompt import LOOKUP_TOOLS, instructions
from .request import PlannerError, PlanRequest
from .review import REVIEW_SCHEMA, plan_json, review_text
from .schema import PLAN_SCHEMA
from .tools import TOOL_SPECS, DrawingTools, ToolInputError, describe_call
from .validation import prepare_plan

MAX_ROUNDS = 8
FALLBACK_BETA = "server-side-fallback-2026-07-01"


def model_name() -> str:
    return config.anthropic_model()


def status() -> tuple[bool, str]:
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False, "pachetul `anthropic` nu este instalat"
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN") or _has_profile():
        return True, f"Claude API · {model_name()}"
    return False, "Setați ANTHROPIC_API_KEY (cheie API Anthropic, facturare per utilizare)."


def _has_profile() -> bool:
    """An `ant auth login` profile on disk (the SDK reads it without an env var)."""
    d = Path.home() / ".config" / "anthropic"
    return d.is_dir() and any(d.iterdir())


def _client():
    import anthropic

    return anthropic.Anthropic(timeout=900.0, max_retries=2)


def _system(req: PlanRequest) -> list:
    return [
        {"type": "text", "text": instructions(LOOKUP_TOOLS)},
        {"type": "text", "text": "=== DRAWING DIGEST ===\n" + req.digest_text, "cache_control": {"type": "ephemeral"}},
    ]


def review(req: PlanRequest, plan: dict, report: str, client=None) -> dict:
    """Second turn on the same cached system prompt: the plan as the model's answer, then what the
    engine measured with it. No lookup tools - the measured report is the new evidence."""
    import anthropic

    client = client or _client()
    model = req.model or model_name()
    messages = [
        {"role": "user", "content": req.request_text()},
        {"role": "assistant", "content": plan_json(plan)},
        {"role": "user", "content": review_text(None, report)},
    ]
    req.say("stage", "AI verifică rezultatele măsurate", detail=f"Claude API · {model} · efort {req.effort}")
    t0 = time.time()
    try:
        with client.beta.messages.stream(
            model=model,
            max_tokens=64000,
            system=_system(req),
            messages=messages,
            thinking={"type": "adaptive", "display": "summarized"},
            output_config={"effort": req.effort, "format": {"type": "json_schema", "schema": REVIEW_SCHEMA}},
            betas=[FALLBACK_BETA],
            fallbacks="default",
        ) as stream:
            for _event in stream:
                if req.cancel.cancelled:
                    break
            req.cancel.check()
            response = stream.get_final_message()
    except anthropic.APIStatusError as e:
        raise PlannerError(f"Claude API {e.status_code}: {getattr(e, 'message', e)}") from e
    except anthropic.APIConnectionError as e:
        raise PlannerError(f"Conexiune eșuată la Claude API: {e}") from e
    if response.stop_reason in ("refusal", "max_tokens"):
        raise PlannerError(f"Verificarea nu a fost finalizată ({response.stop_reason}).")
    text = "".join(b.text for b in response.content if b.type == "text").strip()
    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        raise PlannerError("Claude nu a returnat o verificare JSON validă.") from None
    u = response.usage
    result["_meta"] = {
        "backend": "anthropic",
        "model": model,
        "seconds": round(time.time() - t0, 1),
        "usage": {
            k: getattr(u, k, None)
            for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens", "output_tokens")
        },
    }
    return result


def plan(req: PlanRequest, client=None) -> dict:
    import anthropic

    client = client or _client()
    model = req.model or model_name()
    tools_impl = DrawingTools(req.drawing, req.region, (req.digest or {}).get("catalogue"), req.labels)
    # eager_input_streaming: tool inputs stream as generated; the client validates them (DrawingTools.call)
    tools = [{**spec, "eager_input_streaming": True} for spec in TOOL_SPECS]
    system = _system(req)
    messages: list = [{"role": "user", "content": req.request_text()}]
    req.run_dir.mkdir(parents=True, exist_ok=True)
    (req.run_dir / "prompt.txt").write_text(
        system[0]["text"] + "\n\n" + system[1]["text"] + "\n\n" + messages[0]["content"]
    )

    req.say("stage", "AI analizează desenul și cererea", detail=f"Claude API · {model} · efort {req.effort}")
    t0 = time.time()
    usage = {"input_tokens": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0, "output_tokens": 0}
    lookups = 0
    repaired = False
    json_retries = 0
    with open(req.run_dir / "api.jsonl", "w") as log:
        for rnd in range(MAX_ROUNDS + 2):
            req.cancel.check()
            last = rnd >= MAX_ROUNDS
            kwargs = {
                "model": model,
                "max_tokens": 64000,
                "system": system,
                "tools": tools,
                "messages": messages,
                "thinking": {"type": "adaptive", "display": "summarized"},
                "output_config": {"effort": req.effort, "format": {"type": "json_schema", "schema": PLAN_SCHEMA}},
                "betas": [FALLBACK_BETA],
                "fallbacks": "default",
            }
            if last:
                kwargs["tool_choice"] = {"type": "none"}  # out of lookup rounds: answer now
            thinking_buf: list[str] = []
            try:
                with client.beta.messages.stream(**kwargs) as stream:
                    for event in stream:
                        if req.cancel.cancelled:
                            break
                        if event.type == "content_block_start" and event.content_block.type == "thinking":
                            thinking_buf = []
                        elif event.type == "content_block_delta" and event.delta.type == "thinking_delta":
                            thinking_buf.append(event.delta.thinking)
                        elif event.type == "content_block_stop" and thinking_buf:
                            text = "".join(thinking_buf).strip()
                            if text:
                                req.say("thought", text[:500])
                            thinking_buf = []
                    req.cancel.check()
                    response = stream.get_final_message()
                json_retries = 0
            except ValueError:
                # tool input the SDK could not parse at all: re-issue the turn (bounded)
                json_retries += 1
                if json_retries > 2:
                    raise PlannerError("Modelul a trimis de mai multe ori argumente invalide pentru unelte.") from None
                continue
            except anthropic.APIStatusError as e:
                raise PlannerError(f"Claude API {e.status_code}: {getattr(e, 'message', e)}") from e
            except anthropic.APIConnectionError as e:
                raise PlannerError(f"Conexiune eșuată la Claude API: {e}") from e

            u = response.usage
            for k in usage:
                usage[k] += getattr(u, k, 0) or 0
            log.write(
                json.dumps(
                    {
                        "round": rnd,
                        "stop_reason": response.stop_reason,
                        "usage": {k: getattr(u, k, None) for k in usage},
                    }
                )
                + "\n"
            )
            for b in response.content:
                if b.type == "fallback":
                    req.say("warning", "Cererea a fost preluată de modelul de rezervă al Anthropic.")

            if response.stop_reason == "refusal":
                details = getattr(response, "stop_details", None)
                raise PlannerError(
                    f"Claude a refuzat cererea ({getattr(details, 'category', None) or 'fără categorie'})."
                )
            if response.stop_reason == "max_tokens":
                raise PlannerError("Răspunsul a depășit limita de tokeni.")
            if response.stop_reason == "pause_turn":
                messages.append({"role": "assistant", "content": response.content})
                continue

            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if tool_uses:
                messages.append({"role": "assistant", "content": response.content})
                results = []
                for b in tool_uses:
                    lookups += 1
                    args = b.input if isinstance(b.input, dict) else {}
                    req.say(
                        "lookup",
                        describe_call(b.name, args),
                        id=b.id,
                        detail=json.dumps(args, ensure_ascii=False)[:300],
                    )
                    try:
                        out = tools_impl.call(b.name, b.input)
                        results.append({"type": "tool_result", "tool_use_id": b.id, "content": out})
                        n = json.loads(out).get("total")
                        req.say("lookup_done", f"{n} rezultate" if n is not None else "gata", id=b.id)
                    except ToolInputError as e:
                        results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": b.id,
                                "is_error": True,
                                "content": json.dumps({"INVALID_INPUT": str(e)}),
                            }
                        )
                        req.say("lookup_done", "argumente invalide", id=b.id)
                messages.append({"role": "user", "content": results})
                continue

            text = "".join(b.text for b in response.content if b.type == "text").strip()
            try:
                result = json.loads(text)
            except json.JSONDecodeError:
                raise PlannerError("Claude nu a returnat un plan JSON valid.") from None
            issues = prepare_plan(result, req)
            if issues and not repaired and rnd < MAX_ROUNDS + 1:
                repaired = True
                req.say(
                    "warning",
                    f"Planul are {len(issues)} probleme; AI-ul le corectează.",
                    detail="; ".join(issues)[:500],
                )
                messages.append({"role": "assistant", "content": response.content})
                messages.append(
                    {
                        "role": "user",
                        "content": "The plan references things that do not exist in the "
                        "drawing:\n- " + "\n- ".join(issues) + "\nReturn the full corrected plan.",
                    }
                )
                continue
            result["_meta"] = {
                "backend": "anthropic",
                "model": model,
                "effort": req.effort,
                "seconds": round(time.time() - t0, 1),
                "lookups": lookups,
                "usage": usage,
                "issues": issues,
            }
            req.say(
                "usage",
                f"{usage['input_tokens'] + usage['cache_read_input_tokens'] + usage['cache_creation_input_tokens']:,} "
                f"tokeni intrare ({usage['cache_read_input_tokens']:,} din cache), {usage['output_tokens']:,} ieșire".replace(
                    ",", " "
                ),
            )
            return result
        raise PlannerError("Claude nu a finalizat planul în numărul maxim de pași.")
