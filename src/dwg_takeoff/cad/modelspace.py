"""Model space (or the sheet a drawing was made on) -> features: blocks exploded recursively,
nested blocks placed where they are drawn, callouts and dimensions collected on the way."""

from __future__ import annotations

import numpy as np
from ezdxf.document import Drawing as DxfDocument
from shapely.geometry import Point

from .entities import block_name, entity_color, entity_geometry, insert_point
from .model import Callout, DimensionNote, Feature, LayerInfo

SKIP_TYPES = {
    "DIMENSION",
    "LEADER",
    "MLEADER",
    "MULTILEADER",
    "VIEWPORT",
    "IMAGE",
    "OLE2FRAME",
    "WIPEOUT",
    "POINT",
    "XLINE",
    "RAY",
    "ACAD_PROXY_ENTITY",
    "REGION",
    "3DSOLID",
    "BODY",
    "MESH",
    "SURFACE",
    "TOLERANCE",
    "ACAD_TABLE",
    "ARC_DIMENSION",
    "HELIX",
}


def _iter_virtual(insert, layers: dict, layer: str, color, depth=0):
    """Yield (entity, containing block name, effective layer, effective colour, depth) for an
    INSERT, recursively exploding nested blocks (a nested INSERT is followed by its own entities,
    one level deeper). Entities on layer "0" take the layer of the INSERT that places them;
    BYBLOCK colours take the colour of that INSERT."""
    if depth > 8:
        return
    try:
        inserts = list(insert.multi_insert()) if insert.mcount > 1 else [insert]
    except Exception:
        inserts = [insert]
    for ins in inserts:
        try:
            ents = list(ins.virtual_entities())
        except Exception:
            continue
        for ve in ents:
            vlayer = ve.dxf.layer
            if vlayer == "0":
                vlayer = layer
            vcolor = entity_color(ve, layers, vlayer, color)
            yield ve, block_name(ins.dxf.name), vlayer, vcolor, depth
            if ve.dxftype() == "INSERT":
                yield from _iter_virtual(ve, layers, vlayer, vcolor, depth + 1)


def _attribs(insert) -> dict | None:
    out = {}
    try:
        for a in insert.attribs:
            v = a.plain_text().strip()
            if v:
                out[a.dxf.tag] = v
    except Exception:
        return None
    return out or None


def graphic_bounds(bounds: list) -> tuple[float, float, float, float] | None:
    """Extent of what a block draws. With many parts, the 2nd-98th percentile of the part centres
    (widened by a typical part size) ignores stray entities left far away in the block definition
    (a survey block with one line at the origin and the rest at real coordinates)."""
    bs = [b for b in bounds if b and b[0] == b[0]]
    if not bs:
        return None
    if len(bs) < 20:
        return (min(b[0] for b in bs), min(b[1] for b in bs), max(b[2] for b in bs), max(b[3] for b in bs))
    a = np.asarray(bs, dtype=float)
    cx, cy = (a[:, 0] + a[:, 2]) / 2, (a[:, 1] + a[:, 3]) / 2
    half = float(np.median(np.maximum(a[:, 2] - a[:, 0], a[:, 3] - a[:, 1]))) / 2
    lo_x, hi_x = np.percentile(cx, [2, 98])
    lo_y, hi_y = np.percentile(cy, [2, 98])
    return (float(lo_x) - half, float(lo_y) - half, float(hi_x) + half, float(hi_y) + half)


def _place_block(feats: list, i: int, end: int | None = None) -> None:
    """Symbol libraries often save blocks with a base point far from what they draw (a tree drawn
    40 m away from its insertion point). Such a block is placed at the centre of its graphics, so
    region filters, counts and highlights use where it is seen; other blocks keep their insertion
    point (a door's hinge, a tree's trunk)."""
    bb = graphic_bounds([f.geom.bounds for f in feats[i + 1 : end] if f.kind not in ("text", "block")])
    if bb is None:
        return
    x0, y0, x1, y1 = bb
    m = 0.1 * max(x1 - x0, y1 - y0)
    p = feats[i].geom
    if not (x0 - m <= p.x <= x1 + m and y0 - m <= p.y <= y1 + m):
        feats[i].geom = Point((x0 + x1) / 2, (y0 + y1) / 2)


_DIM_KIND = {0: "linear", 1: "aligned", 2: "angular", 3: "diameter", 4: "radius", 5: "angular"}
MAX_NOTES = 5000


def _xy(v) -> tuple[float, float]:
    return (float(v[0]), float(v[1]))


def read_callout(e, handle: str, layer: str) -> Callout | None:
    """Text and arrow of a LEADER / MULTILEADER (None when it has no usable arrow)."""
    try:
        if e.dxftype() == "LEADER":
            vs = list(e.vertices)
            if len(vs) < 2:
                return None
            text = None
            ah = e.dxf.get("annotation_handle")
            if ah and e.doc is not None:
                note = e.doc.entitydb.get(ah)
                if note is not None and note.dxftype() in ("MTEXT", "TEXT"):
                    text = (note.plain_text() or "").strip() or None
            return Callout(text, _xy(vs[0]), _xy(vs[-1]), layer, handle)
        ctx = e.context  # MULTILEADER
        text = None
        if ctx.mtext is not None and ctx.mtext.default_content:
            from ezdxf.tools.text import plain_mtext

            text = plain_mtext(ctx.mtext.default_content).strip() or None
        if text is None and getattr(e, "block_attribs", None):
            text = " ".join(a.text for a in e.block_attribs if a.text).strip() or None
        tips = [line.vertices[0] for ld in ctx.leaders for line in ld.lines if line.vertices]
        if not tips:
            return None
        end = ctx.mtext.insert if ctx.mtext is not None else ctx.leaders[0].last_leader_point
        return Callout(text, _xy(tips[0]), _xy(end), layer, handle)
    except Exception:
        return None


def read_dimension(e, handle: str, layer: str) -> DimensionNote | None:
    try:
        kind = _DIM_KIND.get(e.dimtype & 0x0F)
        if kind is None:
            return None
        value = e.get_measurement()
        if not isinstance(value, (int, float)):
            return None
        text = (e.dxf.get("text", "") or "").strip()
        if text in ("<>", " "):
            text = ""
        at = e.dxf.get("text_midpoint") or e.dxf.get("defpoint")
        if at is None:
            return None
        try:
            ocs = e.ocs()
            if ocs.transform:
                at = ocs.to_wcs(at)
        except Exception:
            pass
        return DimensionNote(kind, float(value), text, _xy(at), layer, handle)
    except Exception:
        return None


def _note(e, handle: str, layer: str, notes: dict | None) -> None:
    """Collect a callout or dimension (they are not measured geometry)."""
    if notes is None:
        return
    t = e.dxftype()
    if t in ("LEADER", "MULTILEADER", "MLEADER") and len(notes["callouts"]) < MAX_NOTES:
        c = read_callout(e, handle, layer)
        if c:
            notes["callouts"].append(c)
    elif t in ("DIMENSION", "ARC_DIMENSION") and len(notes["dimensions"]) < MAX_NOTES:
        d = read_dimension(e, handle, layer)
        if d:
            notes["dimensions"].append(d)


def measurable_count(layout) -> int:
    return sum(1 for e in layout if e.dxftype() not in SKIP_TYPES and e.dxftype() not in ("TEXT", "MTEXT"))


def extract_model_space(
    doc: DxfDocument, layers: dict[str, LayerInfo], warnings: list[str], layout=None, notes: dict | None = None
) -> list[Feature]:
    """Features of model space (or of `layout`, for drawings made directly on a sheet). Callouts
    and dimensions (also those inside blocks) are collected into `notes` when given."""
    feats: list[Feature] = []

    def vis(*names):
        for n in names:
            li = layers.get(n)
            if li is not None and not li.visible:
                return False
        return True

    def add(handle, layer, dxftype, kind, geom, extra, color, block=None, nested=False, visible=True, attribs=None):
        feats.append(
            Feature(
                fid=len(feats),
                handle=handle,
                layer=layer,
                dxftype=dxftype,
                kind=kind,
                geom=geom,
                pattern=extra.get("pattern"),
                block=block,
                nested=nested,
                text=extra.get("text"),
                text_height=extra.get("height"),
                visible=visible,
                width=extra.get("width"),
                color=color[0],
                aci=color[1],
                attribs=attribs,
            )
        )

    space = layout if layout is not None else doc.modelspace()
    for e in space:
        t = e.dxftype()
        if t in SKIP_TYPES:
            _note(e, e.dxf.handle, e.dxf.layer, notes)
            continue
        handle = e.dxf.handle
        layer = e.dxf.layer
        color = entity_color(e, layers, layer)
        if t == "INSERT":
            ip = insert_point(e)
            blk = doc.blocks.get(e.dxf.name)
            name = block_name(e.dxf.name)
            if blk is not None and blk.block_record and blk.block.is_xref:
                warnings.append(f"External reference '{name}' is not bound into the drawing")
            top = len(feats)
            add(
                handle,
                layer,
                t,
                "block",
                Point(ip.x, ip.y),
                {},
                color,
                block=name,
                visible=vis(layer),
                attribs=_attribs(e),
            )
            for a in e.attribs:
                r = entity_geometry(a)
                if r:
                    add(
                        handle,
                        a.dxf.layer,
                        "ATTRIB",
                        r[0],
                        r[1],
                        r[2],
                        entity_color(a, layers, a.dxf.layer, color),
                        block=name,
                        nested=True,
                        visible=vis(layer, a.dxf.layer),
                    )
            depths: list[int] = []  # nesting depth of each feature added below
            nested_inserts: list[tuple[int, int]] = []
            for ve, parent_block, vlayer, vcolor, depth in _iter_virtual(e, layers, layer, color):
                vt = ve.dxftype()
                if vt in SKIP_TYPES:
                    _note(ve, handle, vlayer, notes)
                    continue
                if vt == "INSERT":
                    vip = insert_point(ve)
                    nested_inserts.append((len(feats), depth))
                    add(
                        handle,
                        vlayer,
                        vt,
                        "block",
                        Point(vip.x, vip.y),
                        {},
                        vcolor,
                        block=block_name(ve.dxf.name),
                        nested=True,
                        visible=vis(layer, vlayer),
                        attribs=_attribs(ve),
                    )
                    depths.append(depth)
                    continue
                r = entity_geometry(ve)
                if r:
                    add(
                        handle,
                        vlayer,
                        vt,
                        r[0],
                        r[1],
                        r[2],
                        vcolor,
                        block=parent_block,
                        nested=True,
                        visible=vis(layer, vlayer),
                    )
                    depths.append(depth)
            start = len(feats) - len(depths)
            for i, d in nested_inserts:
                end = i + 1
                while end < len(feats) and depths[end - start] > d:
                    end += 1
                _place_block(feats, i, end)
            _place_block(feats, top)
            continue
        r = entity_geometry(e)
        if r:
            add(handle, layer, t, r[0], r[1], r[2], color, visible=vis(layer))
    return feats
