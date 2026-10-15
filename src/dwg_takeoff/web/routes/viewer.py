"""What the plan viewer draws: the background image and tiles, single entities, layers."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from shapely.prepared import prep

from ...engine.geojson import geom_to_json, merge
from ..deps import get_project
from ..views import TILE_LEVELS, cached_view, ensure_view, ensure_view_in_background, tile_path, view_bounds, view_paths

router = APIRouter(prefix="/api/projects/{pid}")
IMAGE_CACHE = {"Cache-Control": "max-age=86400"}


@router.get("/view")
def view(pid: str, wait: bool = False):
    """The background image's URL and model window; 202 while it is being rendered."""
    p = get_project(pid)
    m = cached_view(p)
    if m is None:
        if not wait:
            ensure_view_in_background(p)
            return JSONResponse({"ready": False, "bounds": list(view_bounds(p))}, status_code=202)
        m = ensure_view(p)
    png, _ = view_paths(p)
    return {"ready": True, "image": f"/api/projects/{pid}/view.png?v={int(png.stat().st_mtime)}", **m}


@router.get("/view.png")
def view_png(pid: str):
    png, _ = view_paths(get_project(pid))
    if not png.exists():
        raise HTTPException(404, "not rendered yet")
    return FileResponse(png, media_type="image/png", headers=IMAGE_CACHE)


@router.get("/tile/{z}/{i}/{j}.png")
def tile(pid: str, z: int, i: int, j: int):
    """Sharper rendering of one part of the background, for deep zoom."""
    p = get_project(pid)
    if not (1 <= z <= TILE_LEVELS and 0 <= i < 2**z and 0 <= j < 2**z):
        raise HTTPException(404)
    return FileResponse(tile_path(p, z, i, j), media_type="image/png", headers=IMAGE_CACHE)


@router.get("/features/{fid}")
def feature(pid: str, fid: int):
    p = get_project(pid)
    if fid < 0 or fid >= len(p.drawing.features):
        raise HTTPException(404)
    f = p.drawing.features[fid]
    s = p.drawing.unit_scale
    return {
        "fid": f.fid,
        "handle": f.handle,
        "layer": f.layer,
        "kind": f.kind,
        "dxftype": f.dxftype,
        "pattern": f.pattern,
        "block": f.block,
        "nested": f.nested,
        "visible": f.visible,
        "area": f.area * s * s,
        "length": f.length * s,
        "text": f.text,
        "geometry": geom_to_json(f.geom),
    }


@router.get("/layer")
def layer_geometry(pid: str, name: str, site: bool = True, pattern: str | None = None, color: str | None = None):
    """A layer's entities (optionally one pattern / colour, inside the site region) to highlight."""
    p = get_project(pid)
    feats = p.drawing.by_layer().get(name, [])
    if pattern:
        feats = [f for f in feats if (f.pattern or "").lower() == pattern.lower()]
    if color:
        feats = [f for f in feats if (f.color or "").lower() == color.lower()]
    if site and p.focus:
        pf = prep(p.focus["polygon"])
        feats = [f for f in feats if pf.contains(f.geom.representative_point())]
    feats = [f for f in feats if f.kind != "text"][:4000]
    return {
        "layer": name,
        "n": len(feats),
        "geometry": merge(f.geom.boundary if f.kind == "closed" else f.geom for f in feats),
    }
