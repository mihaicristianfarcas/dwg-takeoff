"""Deterministic evaluation of a takeoff plan against the drawing.

Every number in the answer comes from here, together with the evidence needed to check it:
contributing entities (handle, layer, raw and counted value), the formula, the factors and where
they come from, and the geometry to highlight on the plan.

A plan has items; an item has components; a component selects entities with `sources` (filters:
layer, kinds, pattern, colour, block, handles - catalogue entries expand to these), measures them
one way (`MEASURE_UNIT`) and multiplies the result by its factors (thickness, height...).
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from types import SimpleNamespace

from shapely.geometry import Polygon
from shapely.ops import unary_union
from shapely.prepared import prep

from ..cad.georef import transformed_polygon
from ..cad.model import Drawing
from ..cad.tables import table_polygon
from ..formatting import factor_ro, num_ro
from .geojson import geom_to_json, xy
from .measure import (
    AREA_KINDS,
    Contribution,
    measure_area,
    measure_count,
    measure_enclosed_area,
    measure_groups,
    measure_length,
    measure_perimeter,
    measure_strip_area,
)

UNIT_DIM = {"m²": 2, "m": 1, "m³": 3, "buc": 0, "-": 0, "": 0}
MEASURE_DIM = {
    "area": 2,
    "length": 1,
    "perimeter": 1,
    "count": 0,
    "strip_area": 2,
    "enclosed_area": 2,
    "count_groups": 0,
}
MEASURE_UNIT = {
    "area": "m²",
    "length": "m",
    "perimeter": "m",
    "count": "buc",
    "strip_area": "m²",
    "enclosed_area": "m²",
    "count_groups": "buc",
}
LINEAR_KINDS = ("line", *AREA_KINDS)


class TableFeature:
    """A footprint polygon defined by an embedded coordinate table (not drawn in model space).
    `geom` is in the table's coordinate system; `model_geom` is its georeferenced position on the
    plan (None if the tables could not be aligned with the drawing)."""

    kind = "table_polygon"

    def __init__(self, table_id: str, name: str, points, poly: Polygon, transform=None):
        self.table_id, self.name, self.points, self.geom = table_id, name, points, poly
        self.model_geom = None
        if transform is not None and not poly.is_empty:
            self.model_geom = transformed_polygon(poly, transform)


# --------------------------------------------------------------------------------------------
# source resolution
# --------------------------------------------------------------------------------------------


def _layer_lookup(by_layer: dict, name: str | None):
    """Exact layer name, else a case-insensitive match, else (None, similar names)."""
    if name is None:
        return None, None
    if name in by_layer:
        return name, None
    low = {k.lower(): k for k in by_layer}
    if name.lower() in low:
        return low[name.lower()], None
    return None, difflib.get_close_matches(name, list(by_layer), n=3, cutoff=0.75)


def _table_sources(src: dict, drawing: Drawing, transform, warnings: list) -> list[TableFeature]:
    name = (src.get("table_object") or "").strip()
    out = [
        TableFeature(t.tid, obj, pts, table_polygon(pts), transform)
        for t in drawing.tables
        for obj, pts in t.objects.items()
        if obj.strip().lower() == name.lower()
    ]
    if not out:
        warnings.append(f"Obiectul '{name}' nu există în tabelele încorporate.")
    return out


def resolve_source(src: dict, drawing: Drawing, by_layer: dict, region_poly, warnings: list, transform=None) -> list:
    """The entities one source selects (features, or TableFeatures for setting-out objects).
    Problems (unknown layer, nothing matched, hidden layer) are appended to `warnings`."""
    kinds = set(src.get("kinds") or [])
    out: list = []
    if "table_polygon" in kinds or src.get("table_object"):
        out = _table_sources(src, drawing, transform, warnings)
        kinds.discard("table_polygon")
        if not src.get("layer"):
            return out
    layer, suggestions = _layer_lookup(by_layer, src.get("layer"))
    if layer is None and not src.get("layer") and src.get("block"):
        feats = drawing.features  # a block type wherever it is placed (also inside other blocks)
        layer = "*"
    elif layer is None:
        if src.get("layer"):
            msg = f"Stratul '{src.get('layer')}' nu există în desen."
            if suggestions:
                msg += f" Similare: {', '.join(suggestions)}"
            warnings.append(msg)
        return out
    else:
        feats = by_layer[layer]
    if kinds:
        want = set(kinds)
        if "hatch" in want:
            want.add("solid")
        feats = [f for f in feats if f.kind in want]
    if src.get("pattern"):
        p = src["pattern"].lower()
        feats = [f for f in feats if (f.pattern or "").lower() == p]
    scope = src.get("scope")  # catalogue entries: "direct" (drawn in the space) or "nested" (inside blocks)
    if scope == "direct":
        feats = [f for f in feats if not f.nested]
    elif scope == "nested":
        feats = [f for f in feats if f.nested]
    if src.get("block"):
        b = src["block"].lower()
        feats = [f for f in feats if (f.block or "").lower() == b]
    elif scope != "nested":
        # blocks nested inside other blocks belong to their parent symbol (a car inside a
        # parking-row block, a leaf inside a tree): only placed blocks are counted
        feats = [f for f in feats if not (f.kind == "block" and f.nested)]
    if src.get("color"):
        c = src["color"].strip().lower()
        feats = [f for f in feats if (f.color or "").lower() == c]
    if src.get("handles"):
        hs = {h.upper() for h in src["handles"]}
        feats = [f for f in feats if f.handle.upper() in hs]
    samples = getattr(drawing, "legend_handles", None)
    if samples:  # the swatches of a legend drawn in model space are samples, not part of the site
        feats = [f for f in feats if f.handle not in samples]
    if region_poly is not None:
        pr = prep(region_poly)
        feats = [f for f in feats if pr.contains(f.geom.representative_point())]
    if not feats:
        warnings.append(
            f"Nicio entitate pe stratul '{layer}' de tipul {sorted(kinds) or 'oricare'}"
            + (f" cu hașura {src.get('pattern')}" if src.get("pattern") else "")
            + (f" de culoarea {src.get('color')}" if src.get("color") else "")
            + (" în zona amenajată" if region_poly is not None else "")
            + "."
        )
    if any(not f.visible for f in feats):
        warnings.append(
            f"Stratul '{layer}' este înghețat/oprit în desen (ascuns); entitățile lui sunt totuși măsurate."
        )
    out.extend(feats)
    return out


# --------------------------------------------------------------------------------------------
# measuring one component
# --------------------------------------------------------------------------------------------


def _evidence_row(f, c: Contribution, scale_pow: int, s: float) -> dict:
    """One row of the evidence table: an entity (or table object) and what it contributed."""
    if isinstance(f, TableFeature):
        row = {
            "fid": None,
            "handle": None,
            "layer": f"tabel {f.table_id}",
            "kind": "table_polygon",
            "pattern": None,
            "block": f.name,
            "visible": True,
            "raw": round(c.raw * s**scale_pow, 3),
            "counted": round(c.counted * s**scale_pow, 3),
            "note": c.note
            or (
                "poziționat pe plan prin georeferențiere"
                if f.model_geom is not None
                else "coordonate din tabel (nepoziționat pe plan)"
            ),
            "points": f.points,
        }
        if f.model_geom is not None:
            cpt = f.model_geom.centroid
            row["at"] = xy((cpt.x, cpt.y))
            row["geometry"] = geom_to_json(f.model_geom)
        return row
    cpt = f.geom.representative_point()
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
        "color": f.color,
        "raw": round(c.raw * s**scale_pow, 3),
        "counted": round(c.counted * s**scale_pow, 3),
        "note": c.note,
        "at": xy((cpt.x, cpt.y)),
    }


def _tolerance(comp: dict, default: float) -> float:
    tol = comp.get("tolerance_m")
    return default if tol is None else max(0.0, float(tol))


@dataclass
class _Selection:
    """The entities a component selected, split by origin, and the warnings so far."""

    comp: dict
    measure: str
    s: float  # metres per drawing unit
    model: list  # drawn features
    tables: list  # TableFeatures (setting-out objects)
    subtract: list
    warnings: list[str]


@dataclass
class _Measured:
    base: float = 0.0  # metres-based value before factors
    stats: dict = field(default_factory=dict)
    evidence: list = field(default_factory=list)
    overlay: dict = field(default_factory=lambda: {"polygons": [], "lines": [], "points": [], "removed": []})
    counted_geom: object = None  # area actually counted (after subtraction), for the overlap checks


def _area(sel: _Selection) -> _Measured:
    """area: union of the surfaces (overlaps once) minus subtracted surfaces; perimeter: the
    union's boundary. Table footprints add their own area / perimeter."""
    out, s, measure, warnings = _Measured(), sel.s, sel.measure, sel.warnings
    area_feats = [f for f in sel.model if f.kind in AREA_KINDS]
    ignored = len(sel.model) - len(area_feats)
    if ignored:
        warnings.append(
            f"{ignored} entități fără suprafață (linii/blocuri/texte) ignorate la măsurarea de tip {measure}."
        )
    sub_feats = [f for f in sel.subtract if not isinstance(f, TableFeature) and f.kind in AREA_KINDS]
    if measure == "area":
        for tf in sel.subtract:
            if not isinstance(tf, TableFeature):
                continue
            if tf.model_geom is not None and not tf.model_geom.is_empty:
                # a footprint from a setting-out table, positioned on the plan
                sub_feats.append(SimpleNamespace(geom=tf.model_geom, kind="closed"))
            else:
                warnings.append(
                    f"Obiectul '{tf.name}' din tabelele de trasare nu este poziționat pe plan; nu a putut fi scăzut."
                )
        n_flat = sum(1 for f in sel.subtract if not isinstance(f, TableFeature) and f.kind not in AREA_KINDS)
        if n_flat:
            warnings.append(f"{n_flat} entități de scăzut fără suprafață (linii/blocuri/texte) au fost ignorate.")
    m = measure_area(area_feats, sub_feats) if measure == "area" else measure_perimeter(area_feats)
    out.counted_geom = m.geometry if measure == "area" else None
    p = 2 if measure == "area" else 1
    out.base = m.value * s**p
    out.stats = {k: (round(v * s**p, 3) if isinstance(v, float) else v) for k, v in m.stats.items()}
    lookup = {f.fid: f for f in area_feats}
    for c in m.contributions:
        if c.fid is None:
            out.evidence.append(
                {
                    "fid": None,
                    "handle": None,
                    "layer": "(scăzut)" if measure == "area" else "(corecție)",
                    "kind": "",
                    "raw": round(c.raw * s**p, 3),
                    "counted": round(c.counted * s**p, 3),
                    "note": c.note,
                }
            )
        else:
            out.evidence.append(_evidence_row(lookup[c.fid], c, p, s))
    out.overlay["polygons"] = geom_to_json(m.geometry)["polygons"]
    if measure == "perimeter":
        out.overlay["lines"] = geom_to_json(m.geometry.boundary if m.geometry is not None else None)["lines"]
    # table footprints (coordinates in the table's own system - not drawn on the plan)
    for tf in sel.tables:
        if tf.geom.is_empty:
            warnings.append(f"Obiectul '{tf.name}' are mai puțin de 3 puncte utilizabile.")
            continue
        v = tf.geom.area if measure == "area" else tf.geom.length
        out.base += v * s**p
        out.stats["raw_sum"] = round(out.stats.get("raw_sum", 0) + v * s**p, 3)
        out.stats["union"] = round(out.stats.get("union", 0) + v * s**p, 3)
        out.evidence.append(_evidence_row(tf, Contribution(None, v, v), p, s))
        if tf.model_geom is not None:
            g = geom_to_json(tf.model_geom)
            if measure == "area":
                out.overlay["polygons"].extend(g["polygons"])
            else:
                out.overlay["lines"].extend(geom_to_json(tf.model_geom.boundary)["lines"])
                out.overlay["polygons"].extend(g["polygons"])
    if sel.tables:
        out.stats["table_objects"] = len(sel.tables)
    return out


def _length(sel: _Selection) -> _Measured:
    """Total line length; coincident and parallel traces within the tolerance counted once."""
    out, s = _Measured(), sel.s
    tol = _tolerance(sel.comp, 0.3)
    lin = [f for f in sel.model if f.kind in LINEAR_KINDS]
    ignored = len(sel.model) - len(lin)
    if ignored:
        sel.warnings.append(f"{ignored} blocuri/texte ignorate la măsurarea lungimii.")
    excl = [f for f in sel.subtract if not isinstance(f, TableFeature) and f.kind in LINEAR_KINDS]
    m = measure_length(lin, tolerance=tol / s, piece=max(2 * tol, 0.2) / s, exclude=excl)
    out.base = m.value * s
    out.stats = {k: (round(v * s, 3) if isinstance(v, float) and k != "tolerance" else v) for k, v in m.stats.items()}
    out.stats["tolerance"] = tol
    lookup = {f.fid: f for f in lin}
    out.evidence = [_evidence_row(lookup[c.fid], c, 1, s) for c in m.contributions]
    out.overlay["lines"] = geom_to_json(m.geometry)["lines"]
    out.overlay["removed"] = geom_to_json(m.removed)["lines"]
    for tf in sel.tables:
        v = tf.geom.length
        out.base += v * s
        out.evidence.append(_evidence_row(tf, Contribution(None, v, v), 1, s))
        if tf.model_geom is not None:
            out.overlay["lines"].extend(geom_to_json(tf.model_geom.boundary)["lines"])
    return out


def _enclosed_area(sel: _Selection) -> _Measured:
    """Area enclosed by lines that close into loops (gaps up to the tolerance bridged)."""
    out, s = _Measured(), sel.s
    tol = _tolerance(sel.comp, 0.05)
    lin = [f for f in sel.model if f.kind in LINEAR_KINDS]
    m = measure_enclosed_area(lin, snap=tol / s)
    out.base = m.value * s * s
    out.stats = {
        "faces": m.stats["faces"],
        "lines": m.stats["lines"],
        "tolerance": tol,
        "outline_length": round(m.stats["outline_length"] * s, 3),
        "raw_sum": round(m.raw_sum * s, 3),
    }
    if not m.stats["faces"]:
        sel.warnings.append(
            "Liniile alese nu închid nicio suprafață (verificați stratul sau măriți toleranța de închidere)."
        )
    lookup = {f.fid: f for f in lin}
    out.evidence = [_evidence_row(lookup[c.fid], c, 1, s) for c in m.contributions]
    out.overlay["polygons"] = geom_to_json(m.geometry)["polygons"]
    return out


def _count_groups(sel: _Selection) -> _Measured:
    """Symbols drawn without blocks: entities closer than the tolerance form one counted group."""
    out, s = _Measured(), sel.s
    tol = _tolerance(sel.comp, 0.3)
    # only geometry drawn outside blocks: placed blocks are counted with "count"
    loose = [f for f in sel.model if not f.nested and f.kind != "block"]
    if len(loose) < len(sel.model):
        sel.warnings.append(
            f"{len(sel.model) - len(loose)} entități din blocuri nu intră în grupuri (blocurile se numără cu „număr”)."
        )
    m = measure_groups(loose, tol / s)
    out.base = float(m.value)
    out.stats = {"groups": m.stats["groups"], "entities": m.stats["entities"], "tolerance": tol}
    lookup = {f.fid: f for f in loose}
    for c, env in zip(m.contributions, m.stats["envelopes"], strict=True):
        row = _evidence_row(lookup[c.fid], c, 0, 1)
        x0, y0, x1, y1 = env.bounds
        row["note"] = c.note.split(",")[0] + f", {(x1 - x0) * s:.2f} × {(y1 - y0) * s:.2f} m"
        row["geometry"] = geom_to_json(env)
        out.evidence.append(row)
    out.overlay["polygons"] = geom_to_json(m.geometry)["polygons"]
    out.overlay["points"] = [xy((e.centroid.x, e.centroid.y)) for e in m.stats["envelopes"]]
    return out


def _strip_area(sel: _Selection) -> _Measured:
    """Painted area of constant-width polylines (road markings): length × drawn width."""
    out, s = _Measured(), sel.s
    m = measure_strip_area(sel.model)
    out.base = m.value * s * s
    out.stats = {k: (round(v * s * s, 3) if isinstance(v, float) else v) for k, v in m.stats.items()}
    if m.stats["ignored_without_width"]:
        sel.warnings.append(f"{m.stats['ignored_without_width']} entități fără lățime de polilinie au fost ignorate.")
    lookup = {f.fid: f for f in sel.model}
    out.evidence = [_evidence_row(lookup[c.fid], c, 2, s) for c in m.contributions]
    out.overlay["polygons"] = geom_to_json(m.geometry)["polygons"]
    return out


def _count(sel: _Selection) -> _Measured:
    """Number of entities (placed blocks, usually); duplicates at the same position once."""
    out = _Measured()
    texts = [f for f in sel.model if f.kind == "text"]
    if texts and (sel.comp.get("factors") or len(texts) == len(sel.model)):
        sel.warnings.append(
            "Se numără texte: valoarea provine din ce este scris pe planșă, nu dintr-o măsurătoare a geometriei."
        )
    m = measure_count(sel.model)
    out.base = float(m.value) + len(sel.tables)
    out.stats = m.stats
    lookup = {f.fid: f for f in sel.model}
    out.evidence = [_evidence_row(lookup[c.fid], c, 0, 1) for c in m.contributions]
    out.overlay["points"] = geom_to_json(m.geometry)["points"]
    return out


MEASURES = {
    "area": _area,
    "perimeter": _area,
    "length": _length,
    "enclosed_area": _enclosed_area,
    "count_groups": _count_groups,
    "strip_area": _strip_area,
    "count": _count,
}


def _formula(base: float, measure: str, factors: list, value: float, unit: str) -> str:
    """ "1 234,35 m² × 0,08 m (grosime, presupus) = 98,75 m³" """
    parts = [f"{num_ro(base, 0 if measure in ('count', 'count_groups') else 2)} {MEASURE_UNIT.get(measure, '')}"]
    for fct in factors:
        tag = {"assumed": "presupus", "document": "din documente"}.get(fct.get("origin"), "din planșă")
        u = fct.get("unit", "")
        parts.append(f"{factor_ro(fct.get('value'))}{' ' + u if u and u != '-' else ''} ({fct.get('name')}, {tag})")
    return " × ".join(parts) + (f" = {num_ro(value)} {unit}" if factors else "")


def run_component(comp: dict, drawing: Drawing, by_layer: dict, regions: dict, transform=None) -> dict:
    """Measure one component: resolve its sources, measure, apply its factors."""
    warnings: list[str] = []
    region_poly = regions.get(comp.get("region")) if comp.get("region") else None
    feats = []
    for src in comp.get("sources") or []:
        feats.extend(resolve_source(src, drawing, by_layer, region_poly, warnings, transform))
    subtract = []
    for src in comp.get("subtract_sources") or []:
        subtract.extend(resolve_source(src, drawing, by_layer, region_poly, warnings, transform))
    feats = list({id(f): f for f in feats}.values())  # an entity selected by several sources counts once
    measure = comp.get("measure", "area")
    sel = _Selection(
        comp,
        measure,
        drawing.unit_scale,
        [f for f in feats if not isinstance(f, TableFeature)],
        [f for f in feats if isinstance(f, TableFeature)],
        subtract,
        warnings,
    )
    if measure in MEASURES:
        res = MEASURES[measure](sel)
    else:
        res = _Measured()
        warnings.append(f"Tip de măsurare necunoscut '{measure}'.")
    if sel.tables and transform is None:
        warnings.append(
            "Contururile din tabelele de trasare nu au putut fi poziționate pe plan "
            "(valorile se calculează din coordonatele tabelului)."
        )
    if not feats and not warnings:
        warnings.append("Componenta nu are surse.")

    factors = comp.get("factors") or []
    value = res.base
    for fct in factors:
        try:
            value *= float(fct.get("value"))
        except (TypeError, ValueError):
            warnings.append(f"Factorul '{fct.get('name')}' nu are o valoare numerică.")
    dim = MEASURE_DIM.get(measure, 0) + sum(UNIT_DIM.get(f.get("unit", ""), 0) for f in factors)
    unit = {0: "buc" if measure in ("count", "count_groups") else "-", 1: "m", 2: "m²", 3: "m³"}.get(dim, f"m^{dim}")
    return {
        "label": comp.get("label", ""),
        "measure": measure,
        "base_value": round(res.base, 4),
        "base_unit": MEASURE_UNIT.get(measure, ""),
        "factors": factors,
        "value": round(value, 4),
        "unit": unit,
        "formula": _formula(res.base, measure, factors, value, unit),
        "stats": res.stats,
        "evidence": res.evidence,
        "overlay": res.overlay,
        "warnings": warnings,
        "n_entities": len(feats),
        # for the cross checks of execute_plan (removed from the result)
        "_geom_area": (
            unary_union(
                (
                    [res.counted_geom]
                    if res.counted_geom is not None
                    else [f.geom for f in sel.model if f.kind in AREA_KINDS]
                )
                + [tf.model_geom for tf in sel.tables if tf.model_geom is not None]
            )
            if measure in ("area", "perimeter")
            else None
        ),
        "_lines": [f for f in sel.model if f.kind in LINEAR_KINDS] if measure == "length" else None,
        "_excl": [f for f in subtract if not isinstance(f, TableFeature)] if measure == "length" else None,
        "_tol": comp.get("tolerance_m") or 0.3,
    }


# --------------------------------------------------------------------------------------------
# a whole plan
# --------------------------------------------------------------------------------------------


def _item(item: dict, comps: list[dict]) -> dict:
    """An item's total (its components summed when they share a unit), status and formula."""
    warnings = []
    unit = item.get("unit", "")
    value = None
    if comps:
        units = {c["unit"] for c in comps}
        if len(units) > 1:
            warnings.append(f"Componentele au unități diferite {sorted(units)} — nu au fost însumate.")
        else:
            value = round(sum(c["value"] for c in comps), 4)
            if unit and comps[0]["unit"] != unit:
                warnings.append(f"Unitatea calculată {comps[0]['unit']} diferă de unitatea cerută {unit}.")
    assumed = [f for c in comps for f in c["factors"] if f.get("origin") == "assumed"]
    status = item.get("status", "measured")
    if assumed and status == "measured":
        status = "assumption_based"
    if status == "measured" and any(w.startswith("Se numără texte") for c in comps for w in c["warnings"]):
        status = "assumption_based"  # a number read from a label is not a measurement
    if len(comps) > 1 and value is not None:
        nd = 0 if comps[0]["unit"] == "buc" else 2
        formula = " + ".join(f"{num_ro(c['value'], nd)}" for c in comps) + f" = {num_ro(value, nd)} {comps[0]['unit']}"
    elif comps:
        formula = comps[0]["formula"]
    else:
        formula = ""
    return {
        "id": item.get("id"),
        "label": item.get("label"),
        "request_text": item.get("request_text", ""),
        "unit": comps[0]["unit"] if comps and value is not None else unit,
        "value": value,
        "status": status,
        "confidence": item.get("confidence"),
        "reasoning": item.get("reasoning", ""),
        "assumptions": item.get("assumptions", []),
        "questions": item.get("questions", []),
        "formula": formula,
        "components": comps,
        "warnings": warnings,
    }


def _cross_checks(items: list[dict], s: float) -> list[dict]:
    """The same surface / curb counted twice: between items with the same kind of quantity and
    between components of one item. Overlaps between e.g. a paving area and a concrete volume
    under it are expected and not reported."""
    pairs = []
    for i, a in enumerate(items):
        for ia, ca in enumerate(a["components"]):
            for ib, cb in enumerate(a["components"]):
                if ib > ia:
                    pairs.append((a, ca, a, cb))
            for b in items[i + 1 :]:
                for cb in b["components"]:
                    pairs.append((a, ca, b, cb))
    checks = []
    for a, ca, b, cb in pairs:
        if ca["measure"] != cb["measure"] or ca["unit"] != cb["unit"]:
            continue
        where = (
            f"în „{a['label']}”, componentele „{ca['label']}” și „{cb['label']}”"
            if a is b
            else f"„{a['label']}” ({ca['label']}) și „{b['label']}” ({cb['label']})"
        )
        ga, gb = ca.get("_geom_area"), cb.get("_geom_area")
        if ca["measure"] == "area" and ga is not None and gb is not None and not ga.is_empty and not gb.is_empty:
            ov = ga.intersection(gb).area * s * s
            if ov > 0.5:
                checks.append(
                    {
                        "type": "area_overlap",
                        "items": sorted({a["id"], b["id"]}),
                        "value": round(ov, 3),
                        "message": f"Suprafață numărată de două ori: {where} se suprapun pe {num_ro(ov)} m².",
                    }
                )
        la, lb = ca.get("_lines"), cb.get("_lines")
        if ca["measure"] == "length" and la and lb:
            tol = max(ca["_tol"], cb["_tol"])
            pc = max(2 * tol, 0.2) / s
            sep = (
                measure_length(la, tol / s, pc, exclude=ca.get("_excl"), geometry=False).value
                + measure_length(lb, tol / s, pc, exclude=cb.get("_excl"), geometry=False).value
            )
            joint = measure_length(la + lb, tol / s, pc, geometry=False).value
            ov = (sep - joint) * s
            if ov > 0.5:
                checks.append(
                    {
                        "type": "line_overlap",
                        "items": sorted({a["id"], b["id"]}),
                        "value": round(ov, 3),
                        "message": f"Trasee comune/paralele: {where} au {num_ro(ov)} m în comun "
                        f"(același element fizic ar putea fi numărat de două ori).",
                    }
                )
    return checks


def execute_plan(plan: dict, drawing: Drawing, regions: dict, table_transform=None) -> dict:
    """Measure every item of `plan`: {"items": [...], "checks": [...]}. `regions` maps region
    names used by components ("site") to polygons."""
    by_layer = drawing.by_layer()
    items = [
        _item(
            item, [run_component(c, drawing, by_layer, regions, table_transform) for c in item.get("components") or []]
        )
        for item in plan.get("items", [])
    ]
    checks = _cross_checks(items, drawing.unit_scale)
    for it in items:
        for c in it["components"]:
            for k in ("_geom_area", "_lines", "_excl", "_tol"):
                c.pop(k, None)
    return {"items": items, "checks": checks}
