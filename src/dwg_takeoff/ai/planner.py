"""Entry point for AI planning: maps a natural-language takeoff request onto measurable sources.

The model never produces quantities. It returns a *plan* (which catalogue entries / filters to
measure, how, and with which thickness / height factors) that the deterministic executor
evaluates. Backends: `dwg_takeoff.ai` (Codex subscription, Claude API, OpenAI API).

The plan is then measured and shown back to the model (entities matched by every source, overlaps,
unit mismatches), which corrects the items that are wrong (`ai.review`). Set DWG_TAKEOFF_REVIEW=0
to skip this check.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .. import config
from ..cad.model import Drawing
from ..engine.executor import execute_plan
from . import default_backend, run_backend, run_review
from .request import Cancelled, CancelToken, PlannerError, PlanRequest
from .review import apply_review, measurement_report
from .validation import prepare_plan


def make_plan(
    query: str,
    drawing: Drawing,
    digest: dict,
    digest_text: str,
    region,
    run_dir: Path,
    model: str | None = None,
    effort: str | None = None,
    on_event=None,
    backend: str | None = None,
    table_transform=None,
    cancel: CancelToken | None = None,
    project_info: str = "",
    regions: dict | None = None,
    review: bool | None = None,
    labels: dict | None = None,
) -> dict:
    """Ask the chosen AI backend for a takeoff plan, then let it check what the plan measures
    (when `regions` is given and the review is enabled). Inputs/outputs are kept in `run_dir`."""
    backend = backend or default_backend()
    req = PlanRequest(
        query=query,
        drawing=drawing,
        digest=digest,
        digest_text=digest_text,
        region=region,
        table_transform=table_transform,
        run_dir=run_dir,
        effort=effort or "medium",
        model=model,
        emit=on_event or (lambda e: None),
        cancel=cancel or CancelToken(),
        project_info=project_info,
        labels=labels or {},
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    if project_info.strip():
        (run_dir / "project_info.txt").write_text(project_info)  # what the AI read besides the drawing
    plan = run_backend(backend, req)
    meta = plan.setdefault("_meta", {})
    meta["project_info_chars"] = len(project_info.strip())
    meta["issues"] = prepare_plan(plan, req)  # catalogue ids -> engine sources
    req.say(
        "done", "AI a stabilit ce se măsoară", detail=f"{len(plan.get('items', []))} elemente · {meta.get('seconds')} s"
    )
    if regions is not None and (config.review_enabled() if review is None else review):
        plan = _review(backend, req, plan, regions)
    plan["_meta"].update({"run_dir": str(run_dir), "created": datetime.now().isoformat(timespec="seconds")})
    (run_dir / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=1, default=str))
    return plan


def _review(backend: str, req: PlanRequest, plan: dict, regions: dict) -> dict:
    """Measure the plan, show the model what came out, apply its corrections."""
    meta = plan["_meta"]
    req.cancel.check()
    result = execute_plan(plan, req.drawing, regions, req.table_transform)
    report = measurement_report(plan, result, req.drawing, regions, req.table_transform, meta.get("issues"))
    (req.run_dir / "review_report.txt").write_text(report)
    try:
        rev = run_review(backend, req, plan, report)
    except Cancelled:
        raise
    except PlannerError as e:
        req.say(
            "warning",
            "Verificarea rezultatelor nu a putut fi făcută; se păstrează planul inițial.",
            detail=str(e)[:300],
        )
        meta["review"] = {"error": str(e)[:500]}
        return plan
    rmeta = rev.pop("_meta", {})
    (req.run_dir / "review.json").write_text(json.dumps(rev, ensure_ascii=False, indent=1))
    revised, changed = apply_review(plan, rev)
    info = {
        "verdict": rev.get("verdict"),
        "notes": rev.get("notes") or [],
        "changed": changed,
        "seconds": rmeta.get("seconds"),
        "usage": rmeta.get("usage"),
        "lookups": rmeta.get("lookups"),
    }
    if changed:
        issues = prepare_plan(revised, req)
        if len(issues) > len(meta.get("issues") or []):
            # a correction that names things the drawing does not have is worse than no correction
            req.say(
                "warning",
                "Corecturile propuse la verificare nu se potrivesc cu desenul; se păstrează planul inițial.",
                detail="; ".join(issues)[:300],
            )
            info.update(rejected=True, rejected_issues=issues, changed=[])
            meta["review"] = info
            req.say("done", "Verificare încheiată (corecturi respinse)")
            return plan
        (req.run_dir / "plan_first.json").write_text(json.dumps(plan, ensure_ascii=False, indent=1, default=str))
        revised["_meta"] = {**meta, "issues": issues}
        meta = revised["_meta"]
        plan = revised
        req.say(
            "done",
            f"Verificare: {len(changed)} {'element corectat' if len(changed) == 1 else 'elemente corectate'}",
            detail=" ".join(info["notes"])[:500],
        )
    else:
        req.say("done", "Verificare: rezultatele corespund cererii", detail=f"{rmeta.get('seconds')} s")
    meta["review"] = info
    meta["plan_seconds"] = meta.get("seconds")
    meta["seconds"] = round((meta.get("seconds") or 0) + (rmeta.get("seconds") or 0), 1)
    return plan
