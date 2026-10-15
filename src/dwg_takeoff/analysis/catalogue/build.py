"""Building the catalogue: features grouped into entries, measured, linked, classified, numbered."""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict

import numpy as np
import shapely
from shapely.ops import unary_union
from shapely.prepared import prep

from ...cad.georef import transformed_polygon
from ...cad.model import Drawing, Feature
from ...cad.modelspace import graphic_bounds
from ...cad.tables import table_polygon
from ...engine.measure import measure_length
from ..colors import color_name
from .entry import MEASURE, PREFIX, Entry, group_key, sort_key
from .relations import (
    classify_entry,
    extent_area,
    find_duplicates,
    find_edges,
    link_callouts,
    link_dimensions,
    link_legends,
    link_texts,
    named_parts,
)

CONTAINER_M = 15.0  # a placed block drawing more than this (largest side) is a container, not a symbol
CONTAINER_PARTS = 2000  # ... or a smaller one (>= 8 m) with this many parts; a detailed tree is a symbol


# --------------------------------------------------------------------------------------------
# blocks: symbols vs containers
# --------------------------------------------------------------------------------------------


def symbol_extents(drawing: Drawing) -> dict[str, tuple]:
    """Handle of each placed block -> extent of what it draws (robust to stray parts)."""
    nested = [f for f in drawing.features if f.nested and f.kind not in ("text", "block")]
    parts: dict[str, list] = defaultdict(list)
    if nested:
        bounds = shapely.bounds(np.array([f.geom for f in nested], dtype=object))
        for f, b in zip(nested, bounds.tolist(), strict=True):
            parts[f.handle].append(b)
    out = {}
    for h, bs in parts.items():
        bb = graphic_bounds(bs)
        if bb is not None:
            out[h] = (*bb, len(bs))
    return out


def containers(drawing: Drawing, extents: dict) -> dict[str, str]:
    """Placed blocks holding a drawing rather than a symbol: handle -> block name."""
    s = drawing.unit_scale
    out = {}
    for f in drawing.features:
        if f.kind == "block" and not f.nested and f.handle in extents:
            x0, y0, x1, y1, n = extents[f.handle]
            size = max(x1 - x0, y1 - y0) * s
            if size >= CONTAINER_M or (n >= CONTAINER_PARTS and size >= 8.0):
                out[f.handle] = f.block
    return out


# --------------------------------------------------------------------------------------------
# grouping
# --------------------------------------------------------------------------------------------


def group_features(drawing: Drawing, cont: dict[str, str]) -> dict[tuple, list[Feature]]:
    """(kind, layer, pattern, colour, block, in_block) -> features. Colours split a group only
    where a layer really uses several (everything-on-layer-0 drawings); a single colour stays unset
    so the filter keeps matching if the layer colour changes."""
    raw: dict[tuple, list[Feature]] = defaultdict(list)
    nested_names = Counter(f.block for f in drawing.features if f.kind == "block" and f.nested)
    samples = drawing.legend_handles
    for f in drawing.features:
        if f.kind == "text" or f.handle in samples:  # legend swatches are samples, not elements
            continue
        container = cont.get(f.handle) if f.nested else None
        if f.nested and container is None:
            # inside a symbol: the symbol is the countable unit; repeated named parts (trees in a
            # "row" block, chairs around a table) are listed as nested blocks
            if f.kind == "block" and nested_names[f.block] >= 3 and not f.block.startswith(("A$C", "*")):
                raw[("nested_block", None, None, f.block, None)].append(f)
            continue
        if f.kind == "block":
            if f.nested:
                if not f.block.startswith(("A$C", "*")) or nested_names[f.block] >= 2:
                    raw[("nested_block", None, None, f.block, container)].append(f)
            elif f.handle not in cont:
                raw[("block", f.layer, None, f.block, None)].append(f)
            else:
                raw[("block", f.layer, None, f.block, None)].append(f)  # the container itself
        elif f.kind in ("hatch", "solid"):
            raw[("surface", f.layer, f.pattern, None, container)].append(f)
        elif f.kind == "closed":
            raw[("outline", f.layer, None, None, container)].append(f)
            raw[("linear", f.layer, None, None, container)].append(f)  # an outline also has a length
        elif f.kind == "line":
            raw[("linear", f.layer, None, None, container)].append(f)
    groups: dict[tuple, list[Feature]] = {}
    for (kind, layer, pattern, block, in_block), feats in raw.items():
        colours = Counter(f.color for f in feats)
        # blocks too: one symbol in several colours is often several species / types (legend)
        if len(colours) > 1 and kind in ("surface", "outline", "linear", "block"):
            for col in colours:
                groups[(kind, layer, pattern, col, block, in_block)] = [f for f in feats if f.color == col]
        else:
            groups[(kind, layer, pattern, None, block, in_block)] = feats
    return groups


def group_filters(gk, cont_handles: dict[str, list[str]]) -> list[dict]:
    kind, layer, pattern, color, block, in_block = gk
    src = {
        "layer": layer,
        "pattern": pattern,
        "color": color,
        "block": None,
        "table_object": None,
        "handles": None,
        "scope": "direct",
    }
    if in_block is not None:  # content of a container block: its placements' handles
        src.update(scope="nested", handles=cont_handles.get(in_block))
    if kind == "surface":
        return [src | {"kinds": ["hatch"]}]
    if kind == "outline":
        return [src | {"kinds": ["closed"]}]
    if kind == "linear":
        return [src | {"kinds": ["line", "closed"]}]
    if kind == "block":
        return [src | {"kinds": ["block"], "block": block}]
    if kind == "nested_block":
        return [src | {"layer": None, "kinds": ["block"], "block": block, "scope": "nested"}]
    raise ValueError(kind)


# --------------------------------------------------------------------------------------------
# building
# --------------------------------------------------------------------------------------------


def build_catalogue(drawing: Drawing, site=None, table_transform=None) -> dict:

    s = drawing.unit_scale
    s2 = s * s
    ps = prep(site) if site is not None else None
    inside = {}
    if ps is not None:
        pts = shapely.point_on_surface(np.array([f.geom for f in drawing.features], dtype=object))
        flags = shapely.contains_xy(site, shapely.get_x(pts), shapely.get_y(pts))
        inside = {f.fid: bool(v) for f, v in zip(drawing.features, flags, strict=True)}

    def in_site(feats):
        return feats if ps is None else [f for f in feats if inside[f.fid]]

    extents = symbol_extents(drawing)
    cont = containers(drawing, extents)
    cont_handles: dict[str, list[str]] = defaultdict(list)
    for h, name in cont.items():
        cont_handles[name].append(h)
    groups = group_features(drawing, cont)

    entries: list[Entry] = []
    fid_entry: dict[int, list[Entry]] = defaultdict(list)
    for gk, feats in groups.items():
        kind, layer, pattern, color, block, in_block = gk
        site_feats = in_site(feats)
        li = drawing.layers.get(layer) if layer else None
        colours = {f.color for f in feats}
        e = Entry(
            id="",
            key=group_key(gk),
            kind=kind,
            layer=layer,
            filters=group_filters(gk, cont_handles),
            measure=MEASURE[kind],
            n=len(feats),
            n_site=len(site_feats) if ps is not None else None,
            pattern=pattern,
            color=color or (next(iter(colours)) if len(colours) == 1 else None),
            block=block,
            in_block=in_block,
            visible=all(f.visible for f in feats),
        )
        e.color_name = color_name(e.color) if e.color else None
        e.split_color = color is not None
        if kind in ("surface", "outline"):
            e.area = unary_union([f.geom for f in site_feats]).area * s2 if site_feats else 0.0
            e.area_all = e.area if ps is None else sum(f.geom.area for f in feats) * s2  # drawn, overlaps not merged
            if kind == "outline":
                e.length = sum(f.geom.boundary.length for f in site_feats) * s
        elif kind == "linear":
            e.length = sum(f.length for f in site_feats) * s
            if site_feats and len(site_feats) <= 1500 and e.length < 5000:
                # coincident duplicates only (the same line drawn twice), numbers only
                m = measure_length(site_feats, tolerance=0.05 / s, piece=1.0 / s, geometry=False)
                if m.value < 0.98 * m.raw_sum:
                    e.length_dedup = m.value * s
            widths = Counter(round(f.width * s, 3) for f in site_feats if f.width and f.width * s >= 0.02)
            if widths:
                e.width_m = widths.most_common(1)[0][0]
        else:  # blocks
            e.count = len(site_feats)
            if kind == "block":
                sizes = [max(x[2] - x[0], x[3] - x[1]) * s for f in feats if (x := extents.get(f.handle))]
                if sizes:
                    e.size_m = round(statistics.median(sizes), 3)
                tags: dict[str, list] = {}
                for f in feats:
                    for k, v in (f.attribs or {}).items():
                        vals = tags.setdefault(k, [])
                        if v not in vals and len(vals) < 5:
                            vals.append(v)
                e.attributes = dict(list(tags.items())[:8])
        if li is not None and li.description:
            e.descriptions.append(f"layer: {li.description}")
        for b in (block, in_block):
            if b and drawing.block_descriptions.get(b):
                e.descriptions.append(f"block {b}: {drawing.block_descriptions[b]}")
        entries.append(e)
        for f in feats:
            fid_entry[f.fid].append(e)

    for t in drawing.tables:
        for obj, pts in t.objects.items():
            poly = table_polygon(pts)
            e = Entry(
                id="",
                key=f"table|{t.tid}|{obj}",
                kind="table",
                layer=None,
                measure="area",
                filters=[
                    {
                        "layer": None,
                        "kinds": ["table_polygon"],
                        "pattern": None,
                        "color": None,
                        "block": None,
                        "table_object": obj,
                        "handles": None,
                    }
                ],
                n=1,
                area=poly.area * s2 if not poly.is_empty else None,
                block=obj,
            )
            e.area_all = e.area
            e.descriptions.append(f"setting-out table {t.tid}: {t.title}"[:120])
            if table_transform is not None and not poly.is_empty and ps is not None:
                e.n_site = int(site.contains(transformed_polygon(poly, table_transform).centroid))
            entries.append(e)

    max_area = 0.25 * (site.area if site is not None else extent_area(drawing))
    link_legends(drawing, entries)
    named = link_texts(drawing, fid_entry, inside if ps is not None else None, max_area)
    link_callouts(drawing, fid_entry, extents, cont, max_area)
    link_dimensions(drawing, fid_entry, max_area)
    find_duplicates(drawing, entries, groups, in_site)
    find_edges(drawing, entries, groups, in_site)
    for e in entries:
        classify_entry(e)
    entries += named_parts(drawing, entries, groups, named, in_site)
    number_entries(entries, ps is not None)
    return {
        "entries": [e.to_dict() for e in entries],
        "site": ps is not None,
        "containers": sorted(set(cont.values())),
        "stats": {
            "entries": len(entries),
            "callouts": len(drawing.callouts),
            "dimensions": len(drawing.dimensions),
            "legend_samples": len(drawing.legend_handles),
        },
    }


def number_entries(entries: list[Entry], has_site: bool) -> None:
    """Short ids, most relevant first within each kind (inside the site, drawn directly, size)."""

    def weight(e: Entry):
        site = (e.n_site or 0) > 0 if has_site else True
        q = e.area or 0.0
        if e.kind == "linear":
            q = e.length or 0.0
        elif e.kind in ("block", "nested_block"):
            q = float(e.count or 0)
        return (not site, e.in_block is not None, -q, e.key)

    by_kind: dict[str, list[Entry]] = defaultdict(list)
    for e in entries:
        by_kind[e.kind].append(e)
    for kind, lst in by_kind.items():
        if kind == "part":
            continue
        lst.sort(key=weight)
        for i, e in enumerate(lst, 1):
            e.id = f"{PREFIX[kind]}{i}"
    ids = {e.key: e.id for e in entries}
    kids: dict[str, list[Entry]] = defaultdict(list)
    for e in by_kind.get("part", []):
        kids[e.parent].append(e)
    for parent, lst in kids.items():
        for i, e in enumerate(lst, 1):  # already largest first
            e.id = f"{ids[parent]}.{i}"
    ids = {e.key: e.id for e in entries}
    for e in entries:
        for d in e.duplicates + e.edges + e.edge_of:
            d["id"] = ids.get(d["key"])
    entries.sort(key=sort_key)
