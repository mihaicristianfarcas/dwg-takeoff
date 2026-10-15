"""Drawings (projects): upload, list, details, project information, units."""

from __future__ import annotations

import threading
import traceback
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile
from pydantic import BaseModel

from ... import config
from ...ai import backends_status, default_backend
from ...cad import convert
from ...cad.units import CHOICES as UNIT_CHOICES
from ...engine.geojson import geom_to_json
from ...project_info import ProjectInfo
from ...store import STORE, Project
from ..deps import get_project
from ..views import ensure_view, ensure_view_in_background, view_paths

router = APIRouter(prefix="/api")

MAX_REFERENCE_BYTES = 60 * 1024 * 1024


def load_in_background(p: Project, render: bool = True) -> None:
    """Convert, extract and analyse a drawing (then render its view) without blocking a request."""

    def work():
        try:
            STORE.load(p)
            if render:
                ensure_view(p)
        except Exception:  # the project's status and error tell the UI
            traceback.print_exc()

    threading.Thread(target=work, daemon=True).start()


def load_saved_drawings() -> None:
    """At startup: the drawings in the samples folder (the first is the default), then earlier
    uploads, oldest first."""
    config.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    samples = sorted(list(config.SAMPLES_DIR.glob("*.dwg")) + list(config.SAMPLES_DIR.glob("*.dxf")))
    uploads = sorted(
        list(config.UPLOADS_DIR.glob("*.dwg")) + list(config.UPLOADS_DIR.glob("*.dxf")), key=lambda f: f.stat().st_mtime
    )
    for f in samples + uploads:
        load_in_background(STORE.add(f, f.name.split("__", 1)[-1]))


@router.get("/health")
def health():
    backends = backends_status()
    return {
        "backends": backends,
        "default_backend": default_backend(),
        "codex": next(b["available"] for b in backends if b["name"] == "codex"),
        "converter": convert.CONVERTER,
        "converter_ok": convert.converter_available(),
        "converter_hint": convert.INSTALL_HINT,
    }


@router.get("/projects")
def list_projects():
    return [p.info() | {"view_ready": view_paths(p)[0].exists()} for p in STORE.projects.values()]


@router.post("/projects")
async def upload(file: UploadFile):
    name = Path(file.filename or "drawing.dwg").name
    if Path(name).suffix.lower() not in (".dwg", ".dxf"):
        raise HTTPException(400, "Only .dwg and .dxf files are supported")
    config.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    dest = config.UPLOADS_DIR / f"{uuid.uuid4().hex[:8]}__{name}"
    with open(dest, "wb") as f:
        while chunk := await file.read(1 << 20):
            f.write(chunk)
    p = STORE.add(dest, name)
    if p.source_path != dest:
        dest.unlink(missing_ok=True)  # same content already loaded
    load_in_background(p)
    return p.info()


@router.get("/projects/{pid}")
def project(pid: str):
    """A drawing's details; once processed, also what the explorer shows (legends, tables...)."""
    p = get_project(pid, ready=False)
    d = p.info() | {"view_ready": view_paths(p)[0].exists()}
    if p.status == "ready":
        dg = p.digest
        d["focus"] = (
            None
            if not p.focus
            else {
                "polygon": geom_to_json(p.focus["polygon"])["polygons"],
                "twist_deg": p.focus["twist_deg"],
                "sheets": p.focus["sheets"],
            }
        )
        d["legends"] = dg["legends"]
        d["unit_choices"] = UNIT_CHOICES
        d["text_tables"] = dg.get("text_tables", [])
        d["tables"] = [{k: t[k] for k in ("id", "kind", "sheets", "title", "objects", "rows")} for t in dg["tables"]]
        d["sheets"] = [{"layout": s["layout"], "titles": s["titles"]} for s in dg["sheets"]]
        d["notes"] = dg["notes"]
        d["catalogue_size"] = len((dg.get("catalogue") or {}).get("entries", []))  # entries: GET .../catalogue
        d["warnings"] = dg["warnings"]
        d["xrefs_missing"] = dg["xrefs_missing"]
    return d


# --- project information: notes, client answers and reference documents the AI reads --------


class NotesBody(BaseModel):
    notes: str


@router.get("/projects/{pid}/info")
def project_info(pid: str):
    pi = ProjectInfo(get_project(pid, ready=False).cache_dir)
    return {"notes": pi.notes(), "documents": pi.documents()}


@router.put("/projects/{pid}/info")
def set_project_info(pid: str, body: NotesBody):
    ProjectInfo(get_project(pid, ready=False).cache_dir).set_notes(body.notes[:20000])
    return project_info(pid)


@router.post("/projects/{pid}/references")
def add_reference(pid: str, file: UploadFile):
    p = get_project(pid, ready=False)
    data = file.file.read(MAX_REFERENCE_BYTES + 1)
    if len(data) > MAX_REFERENCE_BYTES:
        raise HTTPException(413, "Document prea mare (max. 60 MB)")
    try:
        ProjectInfo(p.cache_dir).add(Path(file.filename or "document").name, data)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return project_info(pid)


@router.delete("/projects/{pid}/references/{rid}")
def delete_reference(pid: str, rid: str):
    try:
        ProjectInfo(get_project(pid, ready=False).cache_dir).remove(rid)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    return project_info(pid)


# --- units ------------------------------------------------------------------------------------


class UnitsBody(BaseModel):
    code: int | None = None  # None (and no scale) = back to the drawing's own units
    scale: float | None = None  # metres per drawing unit, calibrated on a known length


@router.post("/projects/{pid}/units")
def set_units(pid: str, body: UnitsBody):
    """Override the drawing units (e.g. a plan in feet saved as inches). Geometry is not re-read;
    quantities, site region and AI digest are recomputed."""
    p = get_project(pid)
    if body.code is not None and body.code not in UNIT_CHOICES:
        raise HTTPException(400, f"Unknown unit code {body.code}")
    if body.scale is not None and not (1e-6 < body.scale < 1e6):
        raise HTTPException(400, "Scale out of range")
    STORE.set_units(p, body.code, body.scale)
    ensure_view_in_background(p)
    return project(pid)
