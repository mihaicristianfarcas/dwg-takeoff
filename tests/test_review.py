"""The second AI pass: the model sees what the engine measured with its plan and corrects it."""

import json
import stat
import sys
import textwrap

from dwg_takeoff.ai import codex_cli
from dwg_takeoff.ai.planner import make_plan
from dwg_takeoff.ai.review import apply_review, measurement_report
from dwg_takeoff.engine.executor import execute_plan


def src(layer, kinds, pattern=None, block=None):
    return {
        "layer": layer,
        "kinds": kinds,
        "pattern": pattern,
        "color": None,
        "block": block,
        "table_object": None,
        "handles": None,
    }


def item(iid, sources, unit="m²", factors=(), measure="area"):
    return {
        "id": iid,
        "label": iid,
        "request_text": "",
        "unit": unit,
        "status": "measured",
        "confidence": "high",
        "reasoning": "r",
        "assumptions": [],
        "questions": [],
        "components": [
            {
                "label": iid,
                "measure": measure,
                "sources": sources,
                "subtract_sources": [],
                "region": None,
                "tolerance_m": None,
                "factors": list(factors),
            }
        ],
    }


def plan_of(*items):
    return {"language": "ro", "summary": "s", "general_notes": ["n"], "questions_for_user": [], "items": list(items)}


def factor(value, unit):
    return {"name": "f", "value": value, "unit": unit, "origin": "assumed", "note": ""}


def test_report_shows_what_each_source_matched(drawing):
    plan = plan_of(
        item("pavaj", [src("PAVAJ_8CM", ["hatch"])]),
        item("gol", [src("PAVAJ_8CM", ["block"])], unit="buc", measure="count"),
        item("beton", [src("PAVAJ_8CM", ["hatch"])], unit="m³", factors=[factor(0.2, "m²")]),
    )
    res = execute_plan(plan, drawing, {})
    report = measurement_report(plan, res, drawing, {})
    lines = report.splitlines()
    pavaj = lines[lines.index(next(x for x in lines if x.startswith("[pavaj]"))) + 2]
    assert "1 entities" in pavaj and "drawn area 750.00 m²" in pavaj
    assert "matches NOTHING" in report
    assert "m^4" in report and "requested unit m³" in report  # dimension error visible to the reviewer


def test_apply_review_replaces_adds_and_removes():
    plan = plan_of(item("a", []), item("b", []), item("c", []))
    same, changed = apply_review(
        plan,
        {
            "verdict": "ok",
            "items": [item("a", [src("X", ["hatch"])])],
            "remove_ids": ["b"],
            "general_notes": None,
            "questions_for_user": None,
        },
    )
    assert same == plan and changed == []  # "ok" never changes anything
    fixed = item("a", [src("X", ["hatch"])])
    new, changed = apply_review(
        plan,
        {
            "verdict": "revised",
            "items": [fixed, item("d", [])],
            "remove_ids": ["b"],
            "general_notes": None,
            "questions_for_user": ["q?"],
        },
    )
    assert [i["id"] for i in new["items"]] == ["a", "c", "d"]
    assert new["items"][0] == fixed and set(changed) == {"a", "d", "b"}
    assert new["general_notes"] == ["n"] and new["questions_for_user"] == ["q?"]
    assert [i["id"] for i in plan["items"]] == ["a", "b", "c"]  # the original is not modified


FAKE_CODEX = textwrap.dedent("""\
    #!{python}
    import json, sys
    args = sys.argv[1:]
    out = args[args.index("-o") + 1]
    sys.stdin.read()
    def ev(**e): print(json.dumps(e), flush=True)
    ev(type="thread.started", thread_id="t1"); ev(type="turn.started")
    if out == "review.json" and {fail_review}:
        ev(type="turn.failed", error={{"message": "boom"}}); sys.exit(1)
    data = {review} if out == "review.json" else {plan}
    open(out, "w").write(json.dumps(data))
    ev(type="turn.completed", usage={{"input_tokens": 100, "cached_input_tokens": 90, "output_tokens": 5}})
""")


def fake_codex(tmp_path, monkeypatch, plan, review, fail_review=False):
    exe = tmp_path / "codex"
    exe.write_text(
        FAKE_CODEX.format(python=sys.executable, plan=repr(plan), review=repr(review), fail_review=fail_review)
    )
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setattr(codex_cli, "_bin", lambda: str(exe))
    monkeypatch.setattr(codex_cli, "user_model", lambda: "test-model")


def ask(drawing, tmp_path, **kw):
    events = []
    plan = make_plan(
        "pavaj",
        drawing,
        {"layers": []},
        "DIGEST",
        None,
        tmp_path / "run",
        effort="low",
        on_event=events.append,
        backend="codex",
        regions={},
        **kw,
    )
    return plan, events


def test_review_corrects_the_plan(drawing, tmp_path, monkeypatch):
    first = plan_of(item("pavaj", [src("PAVAJ_8CM", ["block"])]))  # wrong kind: measures nothing
    fixed = item("pavaj", [src("PAVAJ_8CM", ["hatch"])])
    fake_codex(
        tmp_path,
        monkeypatch,
        first,
        {
            "verdict": "revised",
            "notes": ["Hașura, nu blocuri."],
            "items": [fixed],
            "remove_ids": [],
            "general_notes": None,
            "questions_for_user": None,
        },
    )
    plan, events = ask(drawing, tmp_path)
    assert plan["items"][0] == fixed
    rv = plan["_meta"]["review"]
    assert rv["verdict"] == "revised" and rv["changed"] == ["pavaj"] and rv["notes"] == ["Hașura, nu blocuri."]
    assert plan["_meta"]["run_dir"] == str(tmp_path / "run") and plan["_meta"]["backend"] == "codex"
    run = tmp_path / "run"
    assert json.loads((run / "plan_first.json").read_text())["items"][0]["components"][0]["sources"][0]["kinds"] == [
        "block"
    ]
    assert "matches NOTHING" in (run / "review_report.txt").read_text()
    # the review prompt starts with the plan prompt, so the model serves it from its prompt cache
    assert (run / "review_prompt.txt").read_text().startswith((run / "prompt.txt").read_text())
    assert next(e.text for e in events if e.kind == "done") == "AI a stabilit ce se măsoară"
    assert execute_plan(plan, drawing, {})["items"][0]["value"] == 750


def test_review_ok_keeps_the_plan(drawing, tmp_path, monkeypatch):
    first = plan_of(item("pavaj", [src("PAVAJ_8CM", ["hatch"])]))
    fake_codex(
        tmp_path,
        monkeypatch,
        first,
        {
            "verdict": "ok",
            "notes": ["Corect."],
            "items": [],
            "remove_ids": [],
            "general_notes": None,
            "questions_for_user": None,
        },
    )
    plan, _ = ask(drawing, tmp_path)
    assert plan["items"] == first["items"] and plan["_meta"]["review"]["changed"] == []
    assert not (tmp_path / "run" / "plan_first.json").exists()


def test_review_that_breaks_the_plan_is_rejected(drawing, tmp_path, monkeypatch):
    first = plan_of(item("pavaj", [src("PAVAJ_8CM", ["hatch"])]))
    bad = item("pavaj", [src("NU_EXISTA", ["hatch"])])
    fake_codex(
        tmp_path,
        monkeypatch,
        first,
        {
            "verdict": "revised",
            "notes": ["x"],
            "items": [bad],
            "remove_ids": [],
            "general_notes": None,
            "questions_for_user": None,
        },
    )
    plan, events = ask(drawing, tmp_path)
    assert plan["items"] == first["items"]
    assert plan["_meta"]["review"]["rejected"] and any(e.kind == "warning" for e in events)


def test_review_failure_keeps_the_first_plan(drawing, tmp_path, monkeypatch):
    first = plan_of(item("pavaj", [src("PAVAJ_8CM", ["hatch"])]))
    fake_codex(tmp_path, monkeypatch, first, {}, fail_review=True)
    plan, events = ask(drawing, tmp_path)
    assert plan["items"] == first["items"] and "boom" in plan["_meta"]["review"]["error"]
    assert any(e.kind == "warning" for e in events)


def test_review_can_be_skipped(drawing, tmp_path, monkeypatch):
    first = plan_of(item("pavaj", [src("PAVAJ_8CM", ["hatch"])]))
    fake_codex(tmp_path, monkeypatch, first, {}, fail_review=True)
    plan, _ = ask(drawing, tmp_path, review=False)
    assert "review" not in plan["_meta"]


def test_plan_by_catalogue_ids(drawing, tmp_path, monkeypatch):
    """The AI answers with catalogue ids; the planner turns them into the entries' filters, keeps
    the ids, and reports ids that do not exist."""
    from dwg_takeoff.analysis.digest import build_digest, digest_to_text

    dg = build_digest(drawing)
    pav = next(e for e in dg["catalogue"]["entries"] if e["layer"] == "PAVAJ_8CM" and e["kind"] == "surface")
    comp = {
        "label": "c",
        "measure": "area",
        "entries": [pav["id"]],
        "subtract_entries": [],
        "sources": [],
        "subtract_sources": [],
        "region": None,
        "tolerance_m": None,
        "factors": [],
    }
    first = plan_of(
        dict(item("pavaj", []), components=[comp]), dict(item("gresit", []), components=[dict(comp, entries=["S404"])])
    )
    fake_codex(
        tmp_path,
        monkeypatch,
        first,
        {
            "verdict": "ok",
            "notes": [],
            "items": [],
            "remove_ids": [],
            "general_notes": None,
            "questions_for_user": None,
        },
    )
    events = []
    plan = make_plan(
        "pavaj",
        drawing,
        dg,
        digest_to_text(dg),
        None,
        tmp_path / "run",
        effort="low",
        on_event=events.append,
        backend="codex",
        regions={},
    )
    src = plan["items"][0]["components"][0]["sources"]
    assert plan["items"][0]["components"][0]["entries"] == [pav["id"]]
    assert len(src) == 1 and src[0]["entry"] == pav["id"] and src[0]["layer"] == "PAVAJ_8CM"
    assert any("S404" in i for i in plan["_meta"]["issues"])
    assert execute_plan(plan, drawing, {})["items"][0]["value"] == 750
    assert (tmp_path / "run" / "catalogue.csv").read_text().startswith("id,kind,layer")
    report = (tmp_path / "run" / "review_report.txt").read_text()
    assert f"entry {pav['id']}" in report and "S404" in report
