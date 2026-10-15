"""Reading single DXF entities: effective colour, measurable geometry, insertion points, texts.

Arcs, splines and polyline bulges are flattened with a chord deviation of `FLATTEN` drawing units.
"""

from __future__ import annotations

import logging
import math
import threading
from functools import reduce
from pathlib import Path

import ezdxf
from ezdxf import bbox as ezbbox
from ezdxf import colors as ezcolors
from ezdxf import path as ezpath
from ezdxf.document import Drawing as DxfDocument
from shapely.geometry import GeometryCollection, LineString, MultiPolygon, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from shapely.validation import make_valid

FLATTEN = 0.01  # max chord deviation (drawing units) when flattening arcs / splines / bulges

# exploding blocks that hold proxy objects logs one warning per object (hundreds per drawing)
logging.getLogger("ezdxf").setLevel(logging.ERROR)


def load_doc(dxf_path: str | Path) -> DxfDocument:
    return ezdxf.readfile(str(dxf_path))


def layer_color(layer) -> tuple[int, int, int]:
    rgb = layer.rgb
    if rgb is not None:
        return tuple(rgb)
    aci = abs(layer.color) or 7
    return tuple(ezcolors.aci2rgb(aci))


def hex_color(rgb) -> str:
    return "#" + "".join(f"{int(v):02x}" for v in rgb[:3])


def entity_color(e, layers: dict, layer: str, parent: tuple[str, int | None] | None = None) -> tuple[str, int | None]:
    """Effective display colour of an entity as ("#rrggbb", ACI or None).

    True colour wins; ACI 256 (BYLAYER) takes the colour of the entity's effective layer; ACI 0
    (BYBLOCK) takes the colour of the containing INSERT (`parent`)."""
    try:
        if e.dxf.hasattr("true_color"):
            return hex_color(e.rgb), None
        aci = e.dxf.get("color", 256)
    except Exception:
        aci = 256
    if aci == 0:
        if parent is not None:
            return parent
        aci = 7
    if aci == 256 or aci is None:
        li = layers.get(layer)
        if li is None:
            return hex_color(ezcolors.aci2rgb(7)), 7
        return hex_color(li.color), li.aci
    aci = abs(int(aci))
    return hex_color(ezcolors.aci2rgb(aci if 0 < aci < 256 else 7)), aci


# --------------------------------------------------------------------------------------------
# geometry helpers
# --------------------------------------------------------------------------------------------


def _polygons_only(g: BaseGeometry) -> BaseGeometry:
    if g.is_empty:
        return g
    if isinstance(g, (Polygon, MultiPolygon)):
        return g
    if isinstance(g, GeometryCollection):
        polys = [p for p in g.geoms if isinstance(p, (Polygon, MultiPolygon))]
        return unary_union(polys) if polys else Polygon()
    return Polygon()


def _ring(pts) -> BaseGeometry:
    if len(pts) < 3:
        return Polygon()
    p = Polygon(pts)
    if not p.is_valid:
        p = _polygons_only(make_valid(p))
    return p


def hatch_geometry(e) -> BaseGeometry:
    rings = []
    for bp in e.paths:
        try:
            pa = ezpath.from_hatch_boundary_path(bp, ocs=e.ocs(), elevation=e.dxf.elevation.z)
            pts = [(v.x, v.y) for v in pa.flattening(FLATTEN)]
        except Exception:
            continue
        r = _ring(pts)
        if not r.is_empty and r.area > 0:
            rings.append(r)
    if not rings:
        return Polygon()
    if e.dxf.get("hatch_style", 0) == 2 and e.dxftype() == "HATCH":  # "ignore" style: islands are filled too
        return unary_union(rings)
    # normal / outer style: even-odd rule
    try:
        return _polygons_only(reduce(lambda a, b: a.symmetric_difference(b), rings))
    except Exception:
        return unary_union(rings)


def path_points(e) -> list[tuple[float, float]]:
    return [(v.x, v.y) for v in ezpath.make_path(e).flattening(FLATTEN)]


def _polyline_width(e) -> float | None:
    try:
        if e.dxftype() == "LWPOLYLINE":
            w = e.dxf.get("const_width", 0) or 0
            if w > 0:
                return float(w)
            ws = {(round(s, 4), round(en, 4)) for _, _, s, en, _ in e.get_points("xyseb")}
        else:
            w = e.dxf.get("default_start_width", 0) or 0
            if w > 0 and w == (e.dxf.get("default_end_width", 0) or 0):
                return float(w)
            ws = {(round(v.dxf.get("start_width", 0), 4), round(v.dxf.get("end_width", 0), 4)) for v in e.vertices}
        if len(ws) == 1:
            s, en = ws.pop()
            if s > 0 and s == en:
                return float(s)
    except Exception:
        pass
    return None


def insert_point(e):
    """Insertion point in world coordinates. TEXT, ATTRIB and INSERT store it in the entity's own
    coordinate system: an entity extruded along -Z (mirrored in 3D) has x = -X, which put such
    blocks and labels on the other side of the origin."""
    p = e.dxf.insert
    if e.dxftype() != "MTEXT":
        try:
            ocs = e.ocs()
            if ocs.transform:
                p = ocs.to_wcs(p)
        except Exception:
            pass
    return p


def entity_geometry(e) -> tuple[str, BaseGeometry, dict] | None:
    """Return (kind, geometry, extra) for a graphical entity, or None if not measurable."""
    t = e.dxftype()
    try:
        if t in ("HATCH", "MPOLYGON"):
            g = hatch_geometry(e)
            if g.is_empty:
                return None
            pattern = "SOLID" if e.dxf.solid_fill else e.dxf.pattern_name
            return "hatch", g, {"pattern": pattern}
        if t in ("SOLID", "TRACE", "3DFACE"):
            v = (
                [e.dxf.vtx0, e.dxf.vtx1, e.dxf.vtx3, e.dxf.vtx2]
                if t != "3DFACE"
                else [e.dxf.vtx0, e.dxf.vtx1, e.dxf.vtx2, e.dxf.vtx3]
            )
            g = _ring([(p.x, p.y) for p in v])
            return ("solid", g, {"pattern": "SOLID"}) if not g.is_empty else None
        if t == "CIRCLE":
            g = _ring(path_points(e))
            return "closed", g, {}
        if t in ("LWPOLYLINE", "POLYLINE"):
            if t == "POLYLINE" and (e.is_poly_face_mesh or e.is_polygon_mesh):
                return None
            pts = path_points(e)
            if len(pts) < 2:
                return None
            closed = e.closed if t == "LWPOLYLINE" else e.is_closed
            if not closed and len(pts) > 3 and math.dist(pts[0], pts[-1]) < 1e-6:
                closed = True
            extra = {}
            w = _polyline_width(e)
            if w:
                extra["width"] = w
            if closed:
                g = _ring(pts)
                if g.is_empty or g.area <= 0:
                    return "line", LineString(pts), extra
                return "closed", g, extra
            return "line", LineString(pts), extra
        if t in ("LINE", "ARC", "SPLINE", "ELLIPSE"):
            pts = path_points(e)
            if len(pts) < 2:
                return None
            if t in ("SPLINE", "ELLIPSE") and len(pts) > 3 and math.dist(pts[0], pts[-1]) < 1e-6:
                g = _ring(pts)
                if not g.is_empty and g.area > 0:
                    return "closed", g, {}
            ls = LineString(pts)
            if ls.length <= 0:
                return None
            return "line", ls, {}
        if t == "MLINE":  # multiline (e.g. walls): measured along its reference line
            pts = [(v.location.x, v.location.y) for v in e.vertices]
            if len(pts) < 2:
                return None
            if e.is_closed:
                g = _ring(pts)
                if not g.is_empty and g.area > 0:
                    return "closed", g, {}
            return "line", LineString(pts), {}
        if t in ("TEXT", "MTEXT", "ATTRIB"):
            txt = e.plain_text()  # resolves %%c, %%d, MTEXT formatting codes
            if not txt or not txt.strip():
                return None
            p = insert_point(e)
            h = e.dxf.get("char_height" if t == "MTEXT" else "height", None)
            return "text", Point(p.x, p.y), {"text": txt.strip(), "height": h}
    except Exception:
        return None
    return None


# --------------------------------------------------------------------------------------------
# block names
# --------------------------------------------------------------------------------------------


def dynamic_block_names(doc: DxfDocument) -> dict[str, str]:
    """Anonymous block (*U12) -> name of the dynamic block it is an instance of ("Door - Metric").
    Every instance of a dynamic block with its own parameters gets its own anonymous block; the
    original name is kept in the block record's AcDbBlockRepBTag xdata."""
    out = {}
    for br in doc.block_records:
        name = br.dxf.name
        if not name.startswith("*U") or not br.has_xdata("AcDbBlockRepBTag"):
            continue
        try:
            for code, val in br.get_xdata("AcDbBlockRepBTag"):
                if code == 1005:
                    rec = doc.entitydb.get(val)
                    if rec is not None and rec.dxf.name:
                        out[name] = rec.dxf.name
        except Exception:
            continue
    return out


_LOCAL = threading.local()  # dynamic block names of the document being extracted (per thread)


def use_block_names(doc: DxfDocument) -> None:
    """Name the anonymous blocks of `doc` after their dynamic block while it is extracted."""
    _LOCAL.names = dynamic_block_names(doc)


def block_name(name: str) -> str:
    return getattr(_LOCAL, "names", {}).get(name, name)


# --------------------------------------------------------------------------------------------
# texts
# --------------------------------------------------------------------------------------------


def text_lines(e) -> list[tuple[str, float, float, float]]:
    """Return (text, x, y_center, height) per visual line of a TEXT/MTEXT (approximate)."""
    t = e.dxftype()
    p = insert_point(e)
    if t == "TEXT" or t == "ATTRIB":
        h = e.dxf.get("height", 2.5)
        try:
            s = (e.plain_text() or "").strip()  # %%u, %%c, %%d control codes resolved
        except Exception:
            s = (e.dxf.text or "").strip()
        return [(s, p.x, p.y + h / 2, h)] if s else []
    h = e.dxf.get("char_height", 2.5)
    spacing = 5 / 3 * h * e.dxf.get("line_spacing_factor", 1.0)
    lines = e.plain_text().split("\n")
    attach = e.dxf.get("attachment_point", 1)
    n = len(lines)
    if attach in (1, 2, 3):  # top
        top = p.y
    elif attach in (4, 5, 6):  # middle
        top = p.y + n * spacing / 2
    else:  # bottom
        top = p.y + n * spacing
    out = []
    for i, s in enumerate(lines):
        s = s.replace("\t", " ").strip()
        if s:
            out.append((s, p.x, top - (i + 0.5) * spacing, h))
    return out


def bbox(entities):
    try:
        b = ezbbox.extents(entities, fast=True)
        return b if b.has_data else None
    except Exception:
        return None


def layout_texts(layout):
    texts = []
    for e in layout:
        t = e.dxftype()
        if t in ("TEXT", "MTEXT"):
            texts.extend((s, x, y, h, e.dxf.layer) for s, x, y, h in text_lines(e))
        elif t == "INSERT":
            for a in e.attribs:
                texts.extend((s, x, y, h, a.dxf.layer) for s, x, y, h in text_lines(a))
    return texts
