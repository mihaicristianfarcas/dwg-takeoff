"""The history of analyses of a drawing: each run is a folder with its prompt, plan and result."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ...engine.executor import execute_plan
from ..deps import get_project, run_dir
from .analysis import expand

router = APIRouter(prefix="/api/projects/{pid}/runs")

# files of a run the UI may show (the run folder also holds logs with more detail)
RUN_FILES = (
    "prompt.txt",
    "plan.json",
    "codex.log",
    "digest.json",
    "features.csv",
    "result.json",
    "project_info.txt",
    "review_report.txt",
    "review.json",
    "plan_first.json",
)


class SaveBody(BaseModel):
    plan: dict
    query: str | None = None
    parent_run: str | None = None


@router.post("")
def save_run(pid: str, body: SaveBody):
    """Save a manually edited plan as a new run (the original AI run stays untouched)."""
    p = get_project(pid)
    folder = p.new_run_dir()
    folder.mkdir(parents=True, exist_ok=True)
    plan = expand(p, dict(body.plan))
    plan["_meta"] = dict(plan.get("_meta") or {}) | {"edited": True, "edited_from": body.parent_run}
    (folder / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=1))
    res = execute_plan(plan, p.drawing, p.regions, p.table_transform)
    res.update({"plan": plan, "query": body.query, "run": folder.name})
    (folder / "result.json").write_text(json.dumps(res, ensure_ascii=False, default=str))
    return res


@router.get("")
def runs(pid: str):
    p = get_project(pid, ready=False)
    out = []
    for d in sorted(p.runs_dir().iterdir(), reverse=True):
        if d.name.startswith("_") or not (d / "result.json").exists():
            continue  # "_deleted_...": removed from the history
        try:
            res = json.loads((d / "result.json").read_text())
        except (OSError, ValueError):
            continue
        meta = res.get("plan", {}).get("_meta") or {}
        out.append(
            {
                "run": d.name,
                "query": res.get("query", ""),
                "items": len(res.get("items", [])),
                "seconds": meta.get("seconds"),
                "edited": bool(meta.get("edited")),
                "backend": meta.get("backend"),
                "effort": meta.get("effort"),
            }
        )
    return out


@router.delete("/{run}")
def delete_run(pid: str, run: str):
    """Remove a run from the history (kept on disk as `_deleted_<run>` for the audit trail)."""
    d = run_dir(get_project(pid, ready=False), run)
    if not d.is_dir():
        raise HTTPException(404)
    d.rename(d.with_name("_deleted_" + d.name))
    return {"deleted": run}


@router.get("/{run}")
def run_result(pid: str, run: str):
    """A past analysis. The saved plan is re-measured with the current engine, so numbers and
    evidence always reflect the latest measurement code (the plan itself is unchanged)."""
    p = get_project(pid, ready=False)
    r = run_dir(p, run) / "result.json"
    if not r.exists():
        raise HTTPException(404)
    saved = json.loads(r.read_text())
    if p.status == "ready" and saved.get("plan"):
        res = execute_plan(saved["plan"], p.drawing, p.regions, p.table_transform)
        res.update({k: saved.get(k) for k in ("plan", "query", "run")})
        return res
    return saved


@router.get("/{run}/{name}")
def run_file(pid: str, run: str, name: str):
    if name not in RUN_FILES:
        raise HTTPException(404)
    f = run_dir(get_project(pid, ready=False), run) / name
    if not f.exists():
        raise HTTPException(404)
    return FileResponse(f, media_type="text/plain; charset=utf-8")
