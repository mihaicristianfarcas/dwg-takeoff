"""What the drawing says about each entry: legend labels, texts and room schedules, callouts,
dimensions, entries drawing the same surface, fills edged by lines, and the vocabulary category."""

from __future__ import annotations

import math
import re
import statistics
from collections import Counter, defaultdict

import numpy as np
import shapely
from shapely import STRtree
from shapely.geometry import Point, box
from shapely.ops import unary_union

from ...cad.model import Drawing, Feature
from ..vocabulary import classify
from .entry import Entry, group_key

MAX_PARTS = 200  # named surfaces listed one by one (rooms, zones) per entry
MAX_NAMES = 4  # more texts than this inside one surface: a sheet frame or a zone with notes
MIN_CATEGORY_SCORE = 2.0
EDGE_TOL_M = 0.5  # a fill's boundary point lies along a line within this (a wall's or a curb's thickness)
EDGE_SHARE = 0.5  # part of the boundary on one line entry to call the fill "edged by" it
EDGE_POINTS = 400  # boundary samples per entry
EDGE_MIN_M2 = (20.0, 4.0)  # entries (whole, typical piece) smaller than this: details, no edges
SCHEDULE_FIT = 0.02  # a room code missing from the schedule: an unmatched row within 2 % names it
_LETTERS = re.compile(r"[^\W\d_]", re.UNICODE)


def _named(text: str | None) -> bool:
    """A text that names something (not a level, number or percentage)."""
    return bool(text) and len(_LETTERS.findall(text)) >= 2


def link_legends(drawing: Drawing, entries: list[Entry]) -> None:
    swatch_kind = {f.handle: f.kind for f in drawing.features if not f.nested and f.handle in drawing.legend_handles}
    for lg in drawing.legends:
        # an empty outline as swatch ("Building": a white rectangle on the walls' layer) shows how
        # the element is drawn: its outlines and the lines of that layer
        outline_swatch = lg.sample == "hatch" and swatch_kind.get(lg.handle) == "closed"
        cands = []
        for e in entries:
            if e.layer != lg.layer or e.in_block:
                continue
            if (
                lg.sample == "hatch"
                and e.kind not in ("surface", "outline")
                and not (outline_swatch and e.kind == "linear")
            ):
                continue
            if lg.sample == "line" and e.kind not in ("linear", "outline"):
                continue
            if lg.sample == "block" and (e.kind != "block" or (lg.block and e.block != lg.block)):
                continue
            if lg.pattern and e.pattern and lg.pattern.lower() != e.pattern.lower():
                continue
            if (
                lg.color
                and e.color
                and lg.color.lower() != e.color.lower()
                and sum(1 for x in entries if x.layer == e.layer and x.kind == e.kind and not x.in_block) > 1
            ):
                continue  # the layer is split by colour: only the swatch's colour
            cands.append(e)
        if lg.sample == "hatch" and any(e.kind == "surface" for e in cands):
            cands = [e for e in cands if e.kind == "surface"]
        if lg.sample == "line" and any(e.kind == "linear" for e in cands):
            cands = [e for e in cands if e.kind == "linear"]
        for e in cands:
            if lg.label not in e.legend:
                e.legend.append(lg.label)


def _text_height(drawing: Drawing) -> float:
    hs = [f.text_height for f in drawing.features if f.kind == "text" and f.text_height and not f.nested]
    return statistics.median(hs) if hs else 2.0 / drawing.unit_scale


def _small_surfaces(drawing: Drawing, max_area: float) -> list[Feature]:
    return [
        f
        for f in drawing.features
        if f.kind in ("hatch", "solid", "closed") and not f.nested and 0 < f.geom.area <= max_area
    ]


def extent_area(drawing: Drawing) -> float:
    """Area of the drawn extent (2nd-98th percentile of entity positions), for drawings without a
    site region: surfaces bigger than a quarter of it are sheet frames or backgrounds."""
    pts = [f.geom.representative_point() for f in drawing.features if not f.nested]
    if len(pts) < 2:
        return float("inf")
    a = np.array([(p.x, p.y) for p in pts])
    (x0, y0), (x1, y1) = np.percentile(a, 2, axis=0), np.percentile(a, 98, axis=0)
    return max((x1 - x0) * (y1 - y0), 1e-9)


def _code(v) -> str | None:
    """A room / object code in a schedule cell: 104, "1.04", "A12" (short, with a digit)."""
    if isinstance(v, float) and v.is_integer() and 0 < v < 100000:
        return str(int(v))
    if isinstance(v, (int, float)):
        return None
    v = str(v).strip()
    return v if 0 < len(v) <= 6 and any(ch.isdigit() for ch in v) and " " not in v else None


def schedule(drawing: Drawing) -> dict[str, list[tuple[str, float | None]]]:
    """code -> [(name, area)] from tables listing "code, name, area" (room schedules, lists of
    objects), drawn as texts or embedded. Several schedules side by side in one row work too; a
    code listed twice (two floors, two schedules) keeps both."""
    out: dict[str, list[tuple[str, float | None]]] = defaultdict(list)
    for t in list(drawing.text_tables) + list(drawing.tables):
        for row in t.rows:
            for i in range(len(row) - 1):
                code = _code(row[i])
                name = row[i + 1]
                if code is None or not isinstance(name, str) or not _named(name):
                    continue
                area = row[i + 2] if i + 2 < len(row) and isinstance(row[i + 2], (int, float)) else None
                item = (name.strip()[:50], float(area) if area is not None else None)
                if item not in out[code]:
                    out[code].append(item)
    return out


def link_texts(drawing: Drawing, fid_entry, inside, max_area) -> dict[int, list[str]]:
    """Texts written inside a surface (room names, zone labels) name it. Codes written inside (room
    numbers) name it through the schedule listing them, when the scheduled areas fit the surface
    (one room, or a kitchen + dining room drawn as one outline); other codes (object marks of a
    setting-out list written on a paving) are kept as information. The tag box drawn around a
    room name is not the room: a surface must be well larger than the text."""
    named: dict[int, list[str]] = defaultdict(list)
    polys = _small_surfaces(drawing, max_area)
    if not polys:
        return named
    tree = STRtree([f.geom for f in polys])
    th0 = _text_height(drawing)
    sched = schedule(drawing)
    s2 = drawing.unit_scale**2
    by_fid = {f.fid: f for f in polys}
    codes: dict[int, list[str]] = defaultdict(list)

    def note(fid, label):
        for e in fid_entry.get(fid, []):
            if e.kind in ("surface", "outline") and label[:70] not in e.texts and len(e.texts) < 8:
                e.texts.append(label[:70])

    unlisted: dict[int, list[tuple[str, str]]] = defaultdict(list)  # codes the schedule lacks
    code_layers: Counter = Counter()  # text layer -> codes found in the schedule
    for t in drawing.features:
        if t.kind != "text" or t.nested or not t.text or (inside is not None and not inside.get(t.fid, True)):
            continue
        label = t.text.strip()
        if label not in sched and not _named(label) and not (sched and _code(label)):
            continue
        th = t.text_height or th0
        hits = [polys[i] for i in tree.query(t.geom, predicate="within")]
        hits = [f for f in hits if f.geom.area >= 30 * th * th]
        if not hits:
            continue
        smallest = min(hits, key=lambda f: f.geom.area)  # the room, not the floor
        if label in sched:
            code_layers[t.layer] += 1
            if label not in codes[smallest.fid]:
                codes[smallest.fid].append(label)
        elif _named(label):
            if label[:70] not in named[smallest.fid]:
                named[smallest.fid].append(label[:70])
            note(smallest.fid, label)
        else:
            unlisted[smallest.fid].append((label, t.layer))
    claimed = set()
    for fid, cs in codes.items():
        a_m2 = by_fid[fid].geom.area * s2
        rows = []
        for c in cs:  # a code listed twice: the line whose area fits its share of the surface
            name, area = min(sched[c], key=lambda x: abs((x[1] or 1e9) - a_m2 / len(cs)))
            rows.append((c, name, area))
        labels = [f"{c} {name}" + (f" (schedule {area:g} m²)" if area else "") for c, name, area in rows]
        total = sum(a for _, _, a in rows if a)
        fits = all(a for _, _, a in rows) and abs(total - a_m2) <= (0.3 if len(rows) == 1 else 0.15) * max(total, a_m2)
        for lab in labels:
            note(fid, lab)
            if fits:
                named[fid].append(lab[:70])
        if fits:
            named[fid].append("\x00room")  # marker: named through a schedule
            claimed.update(rows)
    # a room numbered like the others but missing from the schedule (a typo: two rows "205",
    # the room says "209"): the one schedule row no room took whose area fits names it
    free = [
        (c, name, area) for c, items in sched.items() for name, area in items if area and (c, name, area) not in claimed
    ]
    for fid, items in unlisted.items():
        cs = sorted({c for c, layer in items if code_layers[layer] >= 2})
        if len(cs) != 1 or fid in codes:
            continue
        a_m2 = by_fid[fid].geom.area * s2
        fit = [r for r in free if abs(r[2] - a_m2) <= SCHEDULE_FIT * max(r[2], a_m2)]
        if len(fit) == 1:
            code, name, area = fit[0]
            free.remove(fit[0])
            lab = f"{cs[0]} {name[:30]} (schedule row {code}, {area:g} m²)"
            named[fid] += [lab, "\x00room"]
        else:
            lab = f"{cs[0]} (not in the schedule)"
            named[fid].append(lab)
        note(fid, lab)
    return named


def named_parts(drawing: Drawing, entries: list[Entry], groups, named: dict[int, list[str]], in_site) -> list[Entry]:
    """Surfaces with a name of their own (rooms with their number, zones with a label) become
    entries of their own under their group, so one room can be chosen without handles."""
    s2 = drawing.unit_scale**2
    by_key = {e.key: e for e in entries}
    out = []
    for gk, feats in groups.items():
        if gk[0] not in ("surface", "outline") or len(feats) < 2:
            continue
        parent = by_key[group_key(gk)]
        # a surface holding many texts is a sheet frame or a zone with notes, not a named surface
        mine = [
            f
            for f in in_site(feats)
            if named.get(f.fid) and len([x for x in named[f.fid] if not x.startswith("\x00")]) <= MAX_NAMES
        ]
        for f in sorted(mine, key=lambda f: -f.geom.area)[:MAX_PARTS]:
            labels = [x for x in named[f.fid] if not x.startswith("\x00")]
            p = Entry(
                id="",
                key=f"{parent.key}#{f.handle}",
                kind="part",
                layer=parent.layer,
                measure="area",
                filters=[dict(x, handles=[f.handle]) for x in parent.filters],
                n=1,
                n_site=1 if parent.n_site is not None else None,
                area=f.geom.area * s2,
                pattern=parent.pattern,
                color=f.color,
                color_name=parent.color_name,
                in_block=parent.in_block,
                visible=f.visible,
                texts=labels,
                parent=parent.key,
            )
            p.area_all = p.area
            p.auto_label, p.auto_label_source = " + ".join(labels)[:120], "text"
            if "\x00room" in named[f.fid]:
                p.vocab = [
                    {"category": "room", "score": 3.0, "evidence": ["code written inside, listed in a schedule"]}
                ]
            out.append(p)
        rooms = [x for x in out if x.parent == parent.key and x.vocab and x.vocab[0]["category"] == "room"]
        if len(rooms) >= 2 and (not parent.vocab or parent.vocab[0]["category"] != "room"):
            parent.vocab.insert(
                0,
                {
                    "category": "room",
                    "score": 3.0,
                    "evidence": [f"{len(rooms)} of its surfaces are rooms of the schedule"],
                },
            )
    return out


def link_callouts(drawing: Drawing, fid_entry, extents, cont, max_area) -> None:
    """A leader's arrow names what it touches: a symbol whose drawing contains the tip, else the
    smallest surface under it, else the nearest line within half a text height."""
    if not drawing.callouts:
        return
    th = _text_height(drawing)
    texts = [f for f in drawing.features if f.kind == "text" and not f.nested and _named(f.text)]
    ttree = STRtree([f.geom for f in texts]) if texts else None
    blocks = [
        f
        for f in drawing.features
        if f.kind == "block" and not f.nested and f.handle in extents and f.handle not in cont
    ]
    btree = STRtree([box(*extents[f.handle][:4]) for f in blocks]) if blocks else None
    polys = _small_surfaces(drawing, max_area)
    ptree = STRtree([f.geom for f in polys]) if polys else None
    lines = [f for f in drawing.features if f.kind == "line" and not f.nested]
    ltree = STRtree([f.geom for f in lines]) if lines else None
    for c in drawing.callouts:
        text = c.text
        if not _named(text) and ttree is not None:
            end = Point(c.end)
            i = ttree.nearest(end)
            text = texts[i].text if i is not None and texts[i].geom.distance(end) <= 4 * th else None
        if not _named(text):
            continue
        tip = Point(c.tip)
        target = None
        if ltree is not None:  # arrows touching a line name the line (pipes, conduits, curbs)
            i = ltree.nearest(tip)
            if i is not None and lines[i].geom.distance(tip) <= th / 3:
                target = lines[i]
        if target is None and btree is not None:
            hit = [blocks[i] for i in btree.query(tip.buffer(th / 2), predicate="intersects")]
            if hit:
                target = min(
                    hit,
                    key=lambda f: (
                        (extents[f.handle][2] - extents[f.handle][0]) * (extents[f.handle][3] - extents[f.handle][1])
                    ),
                )
        if target is None and ptree is not None:
            hit = [polys[i] for i in ptree.query(tip, predicate="within")]
            if hit:
                target = min(hit, key=lambda f: f.geom.area)
        if target is None:
            continue
        for e in fid_entry.get(target.fid, []):
            if text[:80] not in e.callouts and len(e.callouts) < 6:
                e.callouts.append(text[:80])


def link_dimensions(drawing: Drawing, fid_entry, max_area) -> None:
    if not drawing.dimensions:
        return
    s = drawing.unit_scale
    polys = _small_surfaces(drawing, max_area)
    if not polys:
        return
    tree = STRtree([f.geom for f in polys])
    for d in drawing.dimensions:
        if d.kind not in ("linear", "aligned", "radius", "diameter"):
            continue
        hits = [polys[i] for i in tree.query(Point(d.at), predicate="within")]
        if not hits:
            continue
        smallest = min(hits, key=lambda f: f.geom.area)
        label = d.text or f"{d.value * s:.2f} m"
        for e in fid_entry.get(smallest.fid, []):
            if e.kind in ("surface", "outline") and label not in e.dims and len(e.dims) < 6:
                e.dims.append(label)


def find_duplicates(drawing: Drawing, entries, groups, in_site) -> None:
    """Entries drawing (nearly) the same surface: a fill and its outline, a frozen copy, the same
    zone on two layers. A small surface lying inside a big one is not a duplicate."""
    s2 = drawing.unit_scale**2
    surf = []
    by_key = {e.key: e for e in entries}
    for gk, feats in groups.items():
        if gk[0] not in ("surface", "outline"):
            continue
        sel = in_site(feats)
        if not sel:
            continue
        u = unary_union([f.geom for f in sel])
        if u.area * s2 >= 0.5:
            surf.append((by_key[group_key(gk)], u))
    if len(surf) < 2:
        return
    tree = STRtree([u.envelope for _, u in surf])
    for i, (ea, ua) in enumerate(surf):
        for j in tree.query(ua.envelope):
            if j <= i:
                continue
            eb, ub = surf[j]
            small, big = sorted((ua.area, ub.area))
            if big > 2 * small:  # no relation kept below can hold
                continue
            if ua.envelope.intersection(ub.envelope).area < 0.5 * small:
                continue
            inter = ua.intersection(ub).area
            if inter <= 0:
                continue
            iou = inter / (ua.area + ub.area - inter)
            if iou > 0.9:
                rel_a = rel_b = "same surface"
            elif inter / small > 0.9 and big <= 1.5 * small:
                rel_a, rel_b = ("inside", "contains") if ua.area < ub.area else ("contains", "inside")
            elif inter / small > 0.5 and big <= 2 * small:
                rel_a = rel_b = "mostly overlaps"
            else:
                continue
            ov = round(inter * s2, 2)
            ea.duplicates.append({"key": eb.key, "relation": rel_a, "overlap_m2": ov})
            eb.duplicates.append({"key": ea.key, "relation": rel_b, "overlap_m2": ov})
    for e in entries:
        e.duplicates.sort(key=lambda d: -d["overlap_m2"])
        del e.duplicates[4:]


def find_edges(drawing: Drawing, entries, groups, in_site) -> None:
    """Fills and outlines whose boundary runs along the lines of another layer: a building hatch
    inside its walls, a road fill between its curbs. The lines draw the element (often with
    details), the fill is its area. Share = part of the surface's boundary (sampled) lying on
    those lines."""
    s = drawing.unit_scale
    by_key = {e.key: e for e in entries}
    lines, owner = [], []
    for gk, feats in groups.items():
        if gk[0] == "linear":
            for f in in_site(feats):
                lines.append(f.geom.boundary if f.kind == "closed" else f.geom)
                owner.append(by_key[group_key(gk)])
    if not lines:
        return
    tree = STRtree(lines)
    for gk, feats in groups.items():
        if gk[0] not in ("surface", "outline"):
            continue
        e = by_key[group_key(gk)]
        sel = in_site(feats)
        piece = statistics.median(f.geom.area for f in sel) * s * s if sel else 0.0
        if (e.area or 0.0) < EDGE_MIN_M2[0] or piece < EDGE_MIN_M2[1]:
            continue
        tol = min(EDGE_TOL_M, 0.1 * math.sqrt(piece)) / s  # small pieces: everything is "near"
        rings = []
        for f in sel:
            for poly in getattr(f.geom, "geoms", [f.geom]):
                if poly.geom_type == "Polygon":
                    rings += [poly.exterior, *poly.interiors]
        total = sum(r.length for r in rings)
        n = int(min(EDGE_POINTS, max(40, total * s / 0.25)))
        pts = np.concatenate(
            [
                shapely.line_interpolate_point(r, np.arange(k) / k, normalized=True)
                for r in rings
                if (k := max(1, round(n * r.length / total)))
            ]
        )
        hits: dict[str, set] = defaultdict(set)
        for p, li in zip(*tree.query(pts, predicate="dwithin", distance=tol), strict=True):
            o = owner[li]
            if o.layer != e.layer:  # the fill's own boundary polylines are not "other lines"
                hits[o.key].add(int(p))
        for key, ps in sorted(hits.items(), key=lambda x: -len(x[1])):
            share = len(ps) / len(pts)
            if share < EDGE_SHARE or len(e.edges) >= 2:
                break
            o = by_key[key]
            e.edges.append({"key": key, "share": round(share, 2), "layer": o.layer, "legend": o.legend[:1]})
            if len(o.edge_of) < 4:
                o.edge_of.append({"key": e.key, "share": round(share, 2)})


def classify_entry(e: Entry) -> None:
    sources = [("legend", x) for x in e.legend] + [("callout", x) for x in e.callouts]
    sources += [
        ("layer_description" if d.startswith("layer") else "block_description", d.split(": ", 1)[-1])
        for d in e.descriptions
    ]
    if e.layer:
        sources.append(("layer", e.layer))
    for b in (e.block, e.in_block):
        if b and e.kind != "table":
            sources.append(("block", b))
    for vals in e.attributes.values():
        sources += [("attribute", str(v)) for v in vals[:2]]
    sources += [("inside_text", t) for t in e.texts[:4]]
    # a category needs real evidence: a legend, a callout, a layer / block name or description
    # (texts written inside a surface alone are too loose: notes mention many things)
    e.vocab = [
        {"category": m.category, "score": round(m.score, 2), "evidence": m.evidence}
        for m in classify(sources)
        if m.score >= MIN_CATEGORY_SCORE
    ]
    if e.legend:
        e.auto_label, e.auto_label_source = e.legend[0], "legend"
    elif e.callouts and e.kind == "block" and len(set(e.callouts)) == 1:
        # a callout names the symbol it points at; on lines and surfaces it often describes
        # something drawn alongside (a conduit along a curb), so it stays information only
        e.auto_label, e.auto_label_source = e.callouts[0], "callout"
    elif e.kind in ("surface", "outline") and len(e.texts) == 1:
        e.auto_label, e.auto_label_source = e.texts[0], "text"
