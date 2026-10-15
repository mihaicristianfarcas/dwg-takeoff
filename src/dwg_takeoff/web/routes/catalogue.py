"""The element catalogue in the UI: entries with their evidence, user labels, entry geometry."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...analysis.catalogue import Labels, entry_index, with_labels
from ...analysis.vocabulary import category_choices
from ...engine.executor import TableFeature, resolve_source
from ...engine.geojson import merge
from ...store import Project
from ..deps import get_project

router = APIRouter(prefix="/api/projects/{pid}")

# entry fields the UI uses (the filters and internal keys stay on the server)
UI_FIELDS = (
    "id",
    "key",
    "kind",
    "layer",
    "in_block",
    "pattern",
    "color",
    "color_name",
    "block",
    "n",
    "n_site",
    "area",
    "length",
    "length_dedup",
    "count",
    "size_m",
    "width_m",
    "visible",
    "legend",
    "callouts",
    "texts",
    "dims",
    "attributes",
    "descriptions",
    "duplicates",
    "edges",
    "edge_of",
    "parent",
    "measure",
    "label",
    "label_source",
    "category",
    "category_source",
    "auto_label",
    "vocab",
    "split_color",
)
MAX_SHAPES = 20000


def _used_in_latest_run(p: Project) -> tuple[str | None, dict[str, list[str]]]:
    """Entry key -> labels of the items that measured it in the latest analysis (a suggestion
    the user can adopt as the entry's label)."""
    for d in sorted(p.runs_dir().iterdir(), reverse=True):
        if d.name.startswith("_") or not (d / "result.json").exists():
            continue
        try:
            plan = json.loads((d / "result.json").read_text()).get("plan") or {}
        except (OSError, ValueError):
            continue
        used: dict[str, list[str]] = {}
        for it in plan.get("items", []):
            for c in it.get("components") or []:
                for src in c.get("sources") or []:
                    k = src.get("entry_key")
                    if k and it.get("label") and it["label"] not in used.setdefault(k, []):
                        used[k].append(it["label"])
        return d.name, used
    return None, {}


@router.get("/catalogue")
def catalogue(pid: str):
    p = get_project(pid)
    cat = p.digest.get("catalogue") or {"entries": []}
    run, used = _used_in_latest_run(p)
    entries = [
        {k: e.get(k) for k in UI_FIELDS} | {"used_in": used.get(e["key"], [])} for e in with_labels(cat, p.labels())
    ]
    return {
        "site": cat.get("site", False),
        "containers": cat.get("containers", []),
        "entries": entries,
        "categories": category_choices(),
        "run": run,
    }


class LabelBody(BaseModel):
    key: str
    label: str | None = None
    category: str | None = None


@router.put("/catalogue/label")
def set_label(pid: str, body: LabelBody):
    p = get_project(pid)
    cat = p.digest.get("catalogue") or {"entries": []}
    if not any(e["key"] == body.key for e in cat["entries"]):
        raise HTTPException(404, "Element necunoscut în catalog.")
    try:
        Labels(p.cache_dir).set(body.key, body.label, body.category)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    p.refresh_text()  # the next AI question sees the corrected label
    e = next(x for x in with_labels(cat, p.labels()) if x["key"] == body.key)
    return {k: e.get(k) for k in UI_FIELDS}


@router.get("/entry/{eid}")
def entry_geometry(pid: str, eid: str):
    """Geometry of one catalogue entry, to highlight it on the plan (placed blocks: what they draw)."""
    p = get_project(pid)
    e = entry_index(p.digest.get("catalogue") or {}).get(eid.upper())
    if e is None:
        raise HTTPException(404, "Element necunoscut în catalog.")
    feats = []
    by_layer = p.drawing.by_layer()
    for f in e["filters"]:
        feats.extend(resolve_source(f, p.drawing, by_layer, None, [], p.table_transform))
    geoms, symbols = [], set()
    for f in feats:
        if isinstance(f, TableFeature):
            if f.model_geom is not None:
                geoms.append(f.model_geom)
        elif f.kind == "block" and not f.nested:
            symbols.add(f.handle)
        else:
            geoms.append(f.geom.boundary if f.kind == "closed" else f.geom)
    if symbols:
        geoms += [
            f.geom for f in p.drawing.features if f.handle in symbols and f.nested and f.kind not in ("text", "block")
        ][:MAX_SHAPES]
    return {"id": e["id"], "n": len(feats), "geometry": merge(geoms[:MAX_SHAPES])}
