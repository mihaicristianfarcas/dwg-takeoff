"""AI layer tests without network: a fake `codex` executable and fake API clients replay the
event/response shapes of the real services."""

import json
import stat
import sys
import textwrap
import threading
import time
from types import SimpleNamespace as NS

import pytest

from dwg_takeoff.ai import anthropic_api, codex_cli, openai_api
from dwg_takeoff.ai.request import Cancelled, CancelToken, PlannerError, PlanRequest
from dwg_takeoff.ai.tools import DrawingTools, ToolInputError
from dwg_takeoff.ai.validation import validate_plan


def plan_json(layer="PAVAJ_8CM"):
    src = {"layer": layer, "kinds": ["hatch"], "pattern": None, "block": None, "table_object": None, "handles": None}
    return {
        "language": "ro",
        "summary": "s",
        "general_notes": [],
        "questions_for_user": [],
        "items": [
            {
                "id": "p8",
                "label": "Pavaj 8 cm",
                "request_text": "pavaj",
                "unit": "m²",
                "status": "measured",
                "confidence": "high",
                "reasoning": "r",
                "assumptions": [],
                "questions": [],
                "components": [
                    {
                        "label": "c",
                        "measure": "area",
                        "sources": [src],
                        "subtract_sources": [],
                        "region": None,
                        "tolerance_m": None,
                        "factors": [],
                    }
                ],
            }
        ],
    }


def make_req(drawing, tmp_path, **kw):
    events = []
    req = PlanRequest(
        query="suprafata de pavaj de 8 cm",
        drawing=drawing,
        digest={"layers": []},
        digest_text="DIGEST",
        region=None,
        table_transform=None,
        run_dir=tmp_path / "run",
        effort="low",
        emit=events.append,
        **kw,
    )
    return req, events


# --------------------------------------------------------------------------------------------
# lookup tools
# --------------------------------------------------------------------------------------------


def test_tools(drawing):
    t = DrawingTools(drawing)
    res = json.loads(t.call("layer_entities", {"layer": "pavaj_8cm", "kind": "hatch", "limit": 10}))
    assert res["layer"] == "PAVAJ_8CM" and res["total"] == 1
    assert res["entities"][0]["area_m2"] == pytest.approx(750)
    missing = json.loads(t.call("layer_entities", {"layer": "PAVAJ8", "kind": None, "limit": 5}))
    assert "PAVAJ_8CM" in missing["similar_layers"]
    texts = json.loads(t.call("search_texts", {"query": "terasa", "limit": 5}))  # diacritics-insensitive
    assert texts["total"] == 1 and "Terasă" in texts["texts"][0]["text"]
    near = json.loads(t.call("entities_near", {"x": 20000, "y": 10000, "radius_m": 1, "limit": 5}))
    assert {e["layer"] for e in near["entities"]} >= {"VERDE"}
    with pytest.raises(ToolInputError):
        t.call("layer_entities", {"layer": "", "kind": None, "limit": 5})
    with pytest.raises(ToolInputError):
        t.call("entities_near", {"x": "a", "y": 0, "radius_m": 1, "limit": 5})


def test_validate_plan(drawing):
    assert validate_plan(plan_json(), drawing) == []
    issues = validate_plan(plan_json("NU_EXISTA"), drawing)
    assert len(issues) == 1 and "NU_EXISTA" in issues[0]


# --------------------------------------------------------------------------------------------
# Codex CLI (fake executable speaking the `codex exec --json` protocol)
# --------------------------------------------------------------------------------------------

FAKE_CODEX = textwrap.dedent("""\
    #!{python}
    import json, sys, time
    args = sys.argv[1:]
    out = args[args.index("-o") + 1]
    sys.stdin.read()
    def ev(**e): print(json.dumps(e), flush=True)
    ev(type="thread.started", thread_id="t1"); ev(type="turn.started")
    ev(type="item.completed", item={{"id": "i0", "type": "agent_message", "text": "Caut stratul pavajului."}})
    ev(type="item.started", item={{"id": "i1", "type": "command_execution", "command": "/bin/zsh -lc 'grep -i pavaj features.csv'", "status": "in_progress"}})
    time.sleep({delay})
    ev(type="item.completed", item={{"id": "i1", "type": "command_execution", "command": "x", "aggregated_output": "a\\nb\\n", "exit_code": 0}})
    plan = {plan}
    open(out, "w").write(json.dumps(plan))
    ev(type="item.completed", item={{"id": "i2", "type": "agent_message", "text": json.dumps(plan)}})
    ev(type="turn.completed", usage={{"input_tokens": 100, "cached_input_tokens": 0, "output_tokens": 50}})
""")


def fake_codex(tmp_path, monkeypatch, delay=0.0):
    exe = tmp_path / "codex"
    exe.write_text(FAKE_CODEX.format(python=sys.executable, delay=delay, plan=repr(plan_json())))
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setattr(codex_cli, "_bin", lambda: str(exe))
    monkeypatch.setattr(codex_cli, "user_model", lambda: "test-model")


def test_codex_events_and_plan(drawing, tmp_path, monkeypatch):
    fake_codex(tmp_path, monkeypatch)
    req, events = make_req(drawing, tmp_path)
    plan = codex_cli.plan(req)
    kinds = [e.kind for e in events]
    assert kinds[0] == "stage" and "thought" in kinds and "lookup" in kinds and "lookup_done" in kinds
    lookup = next(e for e in events if e.kind == "lookup")
    assert lookup.text == "Caută în entitățile planșei" and lookup.detail == "grep -i pavaj features.csv"
    assert plan["items"][0]["id"] == "p8"
    assert plan["_meta"]["backend"] == "codex" and plan["_meta"]["lookups"] == 1
    assert (req.run_dir / "features.csv").exists() and (req.run_dir / "codex.jsonl").exists()


def test_codex_cancel_kills_process(drawing, tmp_path, monkeypatch):
    fake_codex(tmp_path, monkeypatch, delay=30)
    cancel = CancelToken()
    req, _events = make_req(drawing, tmp_path, cancel=cancel)
    threading.Timer(1.0, cancel.cancel).start()
    t = time.time()
    with pytest.raises(Cancelled):
        codex_cli.plan(req)
    assert time.time() - t < 10


# --------------------------------------------------------------------------------------------
# Anthropic API (fake streaming client)
# --------------------------------------------------------------------------------------------


class FakeStream:
    def __init__(self, events, message):
        self.events, self.message = events, message

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        return iter(self.events)

    def get_final_message(self):
        return self.message


def thinking_events(text):
    return [
        NS(type="content_block_start", content_block=NS(type="thinking")),
        NS(type="content_block_delta", delta=NS(type="thinking_delta", thinking=text)),
        NS(type="content_block_stop"),
    ]


def usage():
    return NS(input_tokens=10, cache_read_input_tokens=5, cache_creation_input_tokens=0, output_tokens=7)


class FakeAnthropic:
    def __init__(self):
        self.calls = []
        tool = NS(
            type="tool_use", id="tu1", name="layer_entities", input={"layer": "PAVAJ_8CM", "kind": "hatch", "limit": 5}
        )
        self.script = [
            FakeStream(
                thinking_events("Verific stratul de pavaj."), NS(stop_reason="tool_use", content=[tool], usage=usage())
            ),
            FakeStream(
                [],
                NS(
                    stop_reason="end_turn",
                    content=[NS(type="text", text=json.dumps(plan_json("GRESIT")))],
                    usage=usage(),
                ),
            ),
            FakeStream(
                [], NS(stop_reason="end_turn", content=[NS(type="text", text=json.dumps(plan_json()))], usage=usage())
            ),
        ]
        self.beta = NS(messages=NS(stream=self._stream))

    def _stream(self, **kw):
        self.calls.append(json.loads(json.dumps(kw, default=lambda o: o.__dict__)))
        return self.script.pop(0)


def test_anthropic_tool_loop_and_repair(drawing, tmp_path):
    client = FakeAnthropic()
    req, events = make_req(drawing, tmp_path)
    plan = anthropic_api.plan(req, client=client)
    assert plan["items"][0]["components"][0]["sources"][0]["layer"] == "PAVAJ_8CM"
    first = client.calls[0]
    assert first["output_config"]["format"]["type"] == "json_schema" and first["output_config"]["effort"] == "low"
    assert first["system"][1]["cache_control"] == {"type": "ephemeral"}  # digest is cached
    assert first["fallbacks"] == "default" and first["thinking"]["display"] == "summarized"
    assert all(t["eager_input_streaming"] for t in first["tools"])
    tool_result = client.calls[1]["messages"][-1]["content"][0]
    assert tool_result["tool_use_id"] == "tu1" and json.loads(tool_result["content"])["total"] == 1
    repair = client.calls[2]["messages"][-1]["content"]
    assert "GRESIT" in repair
    kinds = [e.kind for e in events]
    assert "thought" in kinds and "lookup" in kinds and "warning" in kinds
    assert plan["_meta"]["backend"] == "anthropic" and plan["_meta"]["lookups"] == 1


def test_anthropic_refusal_is_reported(drawing, tmp_path):
    client = FakeAnthropic()
    client.script = [
        FakeStream([], NS(stop_reason="refusal", content=[], usage=usage(), stop_details=NS(category="cyber")))
    ]
    req, _ = make_req(drawing, tmp_path)
    with pytest.raises(PlannerError, match="refuzat"):
        anthropic_api.plan(req, client=client)


# --------------------------------------------------------------------------------------------
# OpenAI Responses API (fake client)
# --------------------------------------------------------------------------------------------


class FakeOpenAI:
    def __init__(self):
        self.calls = []
        u = NS(input_tokens=10, output_tokens=5, input_tokens_details=NS(cached_tokens=4))
        call = NS(
            type="function_call",
            name="search_texts",
            arguments=json.dumps({"query": "pavele", "limit": 5}),
            call_id="c1",
        )
        reasoning = NS(type="reasoning", summary=[NS(text="Caut textele despre pavele.", type="summary_text")])
        self.script = [
            NS(id="r1", status="completed", usage=u, output=[reasoning, call], output_text=""),
            NS(
                id="r2",
                status="completed",
                usage=u,
                output=[NS(type="message", content=[])],
                output_text=json.dumps(plan_json()),
            ),
        ]
        self.responses = NS(create=self._create)

    def _create(self, **kw):
        self.calls.append(kw)
        return self.script.pop(0)


def test_openai_function_calls(drawing, tmp_path):
    client = FakeOpenAI()
    req, events = make_req(drawing, tmp_path, model="test-model")
    plan = openai_api.plan(req, client=client)
    assert plan["items"][0]["id"] == "p8"
    first, second = client.calls
    assert first["text"]["format"]["strict"] is True and first["reasoning"]["effort"] == "low"
    assert all(t["strict"] for t in first["tools"])
    assert second["previous_response_id"] == "r1"
    out = second["input"][0]
    assert out["type"] == "function_call_output" and out["call_id"] == "c1"
    assert json.loads(out["output"])["total"] == 1
    assert any(e.kind == "thought" for e in events)


# --------------------------------------------------------------------------------------------
# review turn (second pass over the measured plan)
# --------------------------------------------------------------------------------------------

REVIEW = {
    "verdict": "ok",
    "notes": ["Corect."],
    "items": [],
    "remove_ids": [],
    "general_notes": None,
    "questions_for_user": None,
}


def test_anthropic_review_request(drawing, tmp_path):
    from dwg_takeoff.ai.review import REVIEW_SCHEMA

    client = FakeAnthropic()
    client.script = [
        FakeStream([], NS(stop_reason="end_turn", content=[NS(type="text", text=json.dumps(REVIEW))], usage=usage()))
    ]
    req, events = make_req(drawing, tmp_path)
    out = anthropic_api.review(req, plan_json(), "REPORT", client=client)
    assert out["verdict"] == "ok" and out["_meta"]["backend"] == "anthropic"
    call = client.calls[0]
    assert call["system"][1]["cache_control"] == {"type": "ephemeral"}  # same cached digest as the plan
    roles = [m["role"] for m in call["messages"]]
    assert (
        roles == ["user", "assistant", "user"] and json.loads(call["messages"][1]["content"])["items"][0]["id"] == "p8"
    )
    assert "REPORT" in call["messages"][2]["content"] and "_meta" not in call["messages"][1]["content"]
    assert call["output_config"]["format"]["schema"] == REVIEW_SCHEMA
    assert events[0].kind == "stage"


def test_openai_review_request(drawing, tmp_path):
    client = FakeOpenAI()
    u = NS(input_tokens=10, output_tokens=5, input_tokens_details=NS(cached_tokens=8))
    client.script = [NS(id="r9", status="completed", usage=u, output=[], output_text=json.dumps(REVIEW))]
    req, _ = make_req(drawing, tmp_path, model="test-model")
    out = openai_api.review(req, plan_json(), "REPORT", client=client)
    assert out["verdict"] == "ok"
    call = client.calls[0]
    assert [m["role"] for m in call["input"]] == ["user", "assistant", "user"]
    assert call["text"]["format"]["name"] == "takeoff_review" and call["text"]["format"]["strict"] is True
    assert call["prompt_cache_key"].startswith("dwg-takeoff-")


def test_codex_usage_limit_is_explained():
    msg = codex_cli.friendly_error(
        "You’ve hit your usage limit. Upgrade to Pro (https://chatgpt.com/explore/pro), "
        "visit https://chatgpt.com/settings/usage to purchase more credits or try again at 3:21 PM."
    )
    assert "Limita de utilizare" in msg and "după 3:21 PM" in msg
    assert codex_cli.friendly_error("some other failure") is None


def test_catalogue_search_tool(drawing):
    from dwg_takeoff.analysis.digest import build_digest

    cat = build_digest(drawing)["catalogue"]
    t = DrawingTools(drawing, catalogue=cat)
    res = json.loads(t.call("catalogue_search", {"query": "pavaj_8", "limit": 5}))
    assert res["total"] == 1 and "'PAVAJ_8CM'" in res["entries"][0] and "750.00 m²" in res["entries"][0]
    assert json.loads(DrawingTools(drawing).call("catalogue_search", {"query": "x", "limit": 5}))["total"] == 0
    assert codex_cli.describe_command("grep -i bord catalogue.csv") == "Caută în catalogul planșei"
