"""Asking for quantities: AI jobs, re-measuring an edited plan, Excel export."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from ...ai import backends_status, default_backend
from ...analysis.catalogue import expand_entries
from ...engine.executor import execute_plan
from ...export import result_to_xlsx
from ...store import STORE, Project
from .. import jobs
from ..deps import get_project

router = APIRouter(prefix="/api")
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def expand(p: Project, plan: dict) -> dict:
    """Catalogue ids of a plan (items added from the catalogue, edited plans) -> engine sources."""
    cat = (p.digest or {}).get("catalogue")
    if cat:
        expand_entries(plan, cat)
    return plan


class AskBody(BaseModel):
    query: str
    effort: str | None = None
    model: str | None = None
    backend: str | None = None


@router.post("/projects/{pid}/ask")
def ask(pid: str, body: AskBody):
    """Start an analysis; poll GET /api/jobs/{job} for its progress and result."""
    p = get_project(pid, ready=False)
    if not body.query.strip():
        raise HTTPException(400, "Empty query")
    name = body.backend or default_backend()
    backend = next((b for b in backends_status() if b["name"] == name), None)
    if backend is None:
        raise HTTPException(400, f"Unknown AI backend '{name}'")
    if not backend["available"]:
        raise HTTPException(400, backend["detail"])
    effort = body.effort if body.effort in ("low", "medium", "high") else "medium"
    return {"job": jobs.start(p, body.query, backend, effort, body.model)}


@router.post("/jobs/{jid}/cancel")
def cancel_job(jid: str):
    job = jobs.JOBS.get(jid)
    if not job:
        raise HTTPException(404)
    if job["status"] == "running":
        job["_cancel"].cancel()
    return {"status": job["status"]}


@router.get("/jobs/{jid}")
def job_status(jid: str):
    job = jobs.JOBS.get(jid)
    if not job:
        raise HTTPException(404)
    return jobs.public(job)


class ExecBody(BaseModel):
    plan: dict
    query: str | None = None


@router.post("/projects/{pid}/execute")
def execute(pid: str, body: ExecBody):
    """Measure a plan (edited in the UI) without saving it."""
    p = get_project(pid)
    plan = expand(p, body.plan)
    return execute_plan(plan, p.drawing, p.regions, p.table_transform) | {"plan": plan, "query": body.query}


class ExportBody(BaseModel):
    result: dict
    project_name: str | None = None
    project_id: str | None = None


@router.post("/export/xlsx")
def export_xlsx(body: ExportBody):
    p = STORE.get(body.project_id) if body.project_id else None
    data = result_to_xlsx(body.result, body.project_name or "", p.info() if p is not None else None)
    return Response(
        data, media_type=XLSX, headers={"Content-Disposition": 'attachment; filename="antemasuratoare.xlsx"'}
    )
