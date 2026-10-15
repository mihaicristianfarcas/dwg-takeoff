"""OpenAI API backend (pay-per-use API key) using the Responses API.

Same flow as the Anthropic backend: digest in the instructions (with a stable prompt-cache key per
drawing), read-only lookup tools as strict function tools, final answer constrained to the plan JSON
schema, reasoning summaries as progress events.

Credentials: OPENAI_API_KEY. Model: DWG_TAKEOFF_OPENAI_MODEL (default: the model configured for
Codex, so the API and subscription modes plan with the same model family).
"""

from __future__ import annotations

import hashlib
import json
import os
import time

from .. import config
from .codex_cli import user_model
from .prompt import LOOKUP_TOOLS, instructions
from .request import PlannerError, PlanRequest
from .review import REVIEW_SCHEMA, plan_json, review_text
from .schema import PLAN_SCHEMA
from .tools import TOOL_SPECS, DrawingTools, ToolInputError, describe_call
from .validation import prepare_plan

MAX_ROUNDS = 8


def model_name() -> str | None:
    return config.openai_model() or user_model()


def status() -> tuple[bool, str]:
    try:
        import openai  # noqa: F401
    except ImportError:
        return False, "pachetul `openai` nu este instalat"
    if not os.environ.get("OPENAI_API_KEY"):
        return False, "Setați OPENAI_API_KEY (cheie API OpenAI, facturare per utilizare)."
    if not model_name():
        return False, "Setați DWG_TAKEOFF_OPENAI_MODEL (modelul OpenAI de folosit)."
    return True, f"OpenAI API · {model_name()}"


def _client():
    import openai

    return openai.OpenAI(timeout=900.0, max_retries=2)


def _tools() -> list[dict]:
    return [
        {
            "type": "function",
            "name": s["name"],
            "description": s["description"],
            "parameters": s["input_schema"],
            "strict": True,
        }
        for s in TOOL_SPECS
    ]


def _instructions(req: PlanRequest) -> tuple[str, str]:
    instr = instructions(LOOKUP_TOOLS) + "\n\n=== DRAWING DIGEST ===\n" + req.digest_text
    return instr, "dwg-takeoff-" + hashlib.sha256(instr.encode()).hexdigest()[:16]


def review(req: PlanRequest, plan: dict, report: str, client=None) -> dict:
    """Second request with the same instructions (prompt cache): the plan as the model's answer,
    then what the engine measured with it."""
    import openai

    client = client or _client()
    model = req.model or model_name()
    instr, cache_key = _instructions(req)
    inputs = [
        {"role": "user", "content": req.request_text()},
        {"role": "assistant", "content": plan_json(plan)},
        {"role": "user", "content": review_text(None, report)},
    ]
    req.say("stage", "AI verifică rezultatele măsurate", detail=f"OpenAI API · {model} · efort {req.effort}")
    t0 = time.time()
    try:
        resp = client.responses.create(
            model=model,
            instructions=instr,
            input=inputs,
            prompt_cache_key=cache_key,
            store=False,
            text={"format": {"type": "json_schema", "name": "takeoff_review", "schema": REVIEW_SCHEMA, "strict": True}},
            reasoning={"effort": req.effort, "summary": "auto"},
        )
    except openai.APIStatusError as e:
        raise PlannerError(f"OpenAI API {e.status_code}: {getattr(e, 'message', e)}") from e
    except openai.APIConnectionError as e:
        raise PlannerError(f"Conexiune eșuată la OpenAI API: {e}") from e
    req.cancel.check()
    if resp.status == "incomplete":
        raise PlannerError(f"Verificare incompletă de la OpenAI ({getattr(resp.incomplete_details, 'reason', None)}).")
    try:
        result = json.loads(resp.output_text)
    except (json.JSONDecodeError, TypeError):
        raise PlannerError("OpenAI nu a returnat o verificare JSON validă.") from None
    u = resp.usage
    result["_meta"] = {
        "backend": "openai",
        "model": model,
        "seconds": round(time.time() - t0, 1),
        "usage": {"input_tokens": getattr(u, "input_tokens", None), "output_tokens": getattr(u, "output_tokens", None)},
    }
    return result


def plan(req: PlanRequest, client=None) -> dict:
    import openai

    client = client or _client()
    model = req.model or model_name()
    if not model:
        raise PlannerError("Nu este configurat niciun model OpenAI (DWG_TAKEOFF_OPENAI_MODEL).")
    tools_impl = DrawingTools(req.drawing, req.region, (req.digest or {}).get("catalogue"), req.labels)
    instr, cache_key = _instructions(req)
    req.run_dir.mkdir(parents=True, exist_ok=True)
    (req.run_dir / "prompt.txt").write_text(instr + "\n\n" + req.request_text())
    text_format = {"format": {"type": "json_schema", "name": "takeoff_plan", "schema": PLAN_SCHEMA, "strict": True}}

    req.say("stage", "AI analizează desenul și cererea", detail=f"OpenAI API · {model} · efort {req.effort}")
    t0 = time.time()
    usage = {"input_tokens": 0, "cached_tokens": 0, "output_tokens": 0}
    lookups = 0
    repaired = False
    inputs: list = [{"role": "user", "content": req.request_text()}]
    prev_id = None
    with open(req.run_dir / "api.jsonl", "w") as log:
        for rnd in range(MAX_ROUNDS + 2):
            req.cancel.check()
            kwargs = {
                "model": model,
                "instructions": instr,
                "input": inputs,
                "tools": _tools(),
                "text": text_format,
                "reasoning": {"effort": req.effort, "summary": "auto"},
                "prompt_cache_key": cache_key,
                "store": True,
            }
            if prev_id:
                kwargs["previous_response_id"] = prev_id
            if rnd >= MAX_ROUNDS:
                kwargs["tool_choice"] = "none"  # out of lookup rounds: answer now
            try:
                resp = client.responses.create(**kwargs)
            except openai.APIStatusError as e:
                raise PlannerError(f"OpenAI API {e.status_code}: {getattr(e, 'message', e)}") from e
            except openai.APIConnectionError as e:
                raise PlannerError(f"Conexiune eșuată la OpenAI API: {e}") from e
            req.cancel.check()
            u = resp.usage
            if u is not None:
                usage["input_tokens"] += u.input_tokens or 0
                usage["output_tokens"] += u.output_tokens or 0
                details = getattr(u, "input_tokens_details", None)
                usage["cached_tokens"] += (getattr(details, "cached_tokens", 0) or 0) if details else 0
            log.write(json.dumps({"round": rnd, "id": resp.id, "status": resp.status, "usage": usage}) + "\n")

            if resp.status == "incomplete":
                reason = getattr(resp.incomplete_details, "reason", None)
                raise PlannerError(f"Răspuns incomplet de la OpenAI ({reason}).")
            calls = []
            for item in resp.output:
                if item.type == "reasoning":
                    for s in item.summary or []:
                        if getattr(s, "text", "").strip():
                            req.say("thought", s.text.strip()[:500])
                elif item.type == "function_call":
                    calls.append(item)
                elif item.type == "message":
                    for c in item.content or []:
                        if c.type == "refusal":
                            raise PlannerError(f"Modelul a refuzat cererea: {c.refusal}")
            prev_id = resp.id
            if calls:
                inputs = []
                for c in calls:
                    lookups += 1
                    try:
                        args = json.loads(c.arguments or "{}")
                    except json.JSONDecodeError:
                        args = None
                    req.say("lookup", describe_call(c.name, args or {}), id=c.call_id, detail=(c.arguments or "")[:300])
                    try:
                        if args is None:
                            raise ToolInputError("arguments are not valid JSON")
                        out = tools_impl.call(c.name, args)
                        n = json.loads(out).get("total")
                        req.say("lookup_done", f"{n} rezultate" if n is not None else "gata", id=c.call_id)
                    except ToolInputError as e:
                        out = json.dumps({"INVALID_INPUT": str(e)})
                        req.say("lookup_done", "argumente invalide", id=c.call_id)
                    inputs.append({"type": "function_call_output", "call_id": c.call_id, "output": out})
                continue

            try:
                result = json.loads(resp.output_text)
            except (json.JSONDecodeError, TypeError):
                raise PlannerError("OpenAI nu a returnat un plan JSON valid.") from None
            issues = prepare_plan(result, req)
            if issues and not repaired and rnd < MAX_ROUNDS + 1:
                repaired = True
                req.say(
                    "warning",
                    f"Planul are {len(issues)} probleme; AI-ul le corectează.",
                    detail="; ".join(issues)[:500],
                )
                inputs = [
                    {
                        "role": "user",
                        "content": "The plan references things that do not exist in the drawing:\n- "
                        + "\n- ".join(issues)
                        + "\nReturn the full corrected plan.",
                    }
                ]
                continue
            result["_meta"] = {
                "backend": "openai",
                "model": model,
                "effort": req.effort,
                "seconds": round(time.time() - t0, 1),
                "lookups": lookups,
                "usage": usage,
                "issues": issues,
            }
            req.say(
                "usage",
                f"{usage['input_tokens']:,} tokeni intrare ({usage['cached_tokens']:,} din cache), "
                f"{usage['output_tokens']:,} ieșire".replace(",", " "),
            )
            return result
        raise PlannerError("OpenAI nu a finalizat planul în numărul maxim de pași.")
