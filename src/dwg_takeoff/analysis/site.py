"""The site region: the part of model space the detailed sheets show.

A site plan file often holds more than the site (location plans, details, other projects drawn
next to it). The region is the model window of the most detailed, most repeated viewports; the
catalogue and the AI work inside it.
"""

from __future__ import annotations

import math
from collections import defaultdict

import numpy as np
from shapely import points
from shapely.geometry import Polygon
from shapely.ops import unary_union

from ..cad.model import Drawing, ViewportInfo


def viewport_polygon(center, width, height, twist_deg) -> Polygon:
    """Model-space window of a viewport (rotated by its twist)."""
    a = math.radians(-twist_deg)
    ca, sa = math.cos(a), math.sin(a)
    corners = ((-width / 2, -height / 2), (width / 2, -height / 2), (width / 2, height / 2), (-width / 2, height / 2))
    return Polygon([(center[0] + dx * ca - dy * sa, center[1] + dx * sa + dy * ca) for dx, dy in corners])


def plot_denominator(vp: ViewportInfo, unit_scale: float) -> float | None:
    """N of the viewport's plot scale 1:N."""
    if vp.denominator:
        return vp.denominator
    return 1000 * unit_scale / vp.scale if vp.scale else None  # older cache: paper in mm assumed


def focus_region(drawing: Drawing) -> dict | None:
    """The model window shown by the most detailed, most repeated viewports (site plans are
    plotted at 1:100-1:500; location plans and overviews at 1:1000 and smaller are ignored, unless
    nothing more detailed exists). None when the drawing has no such viewport."""
    if drawing.space != "Model":
        return None
    s = drawing.unit_scale
    cands = []
    for limit in (999.9, 2500):
        for lo in drawing.layouts:
            for vp in lo.viewports:
                d = plot_denominator(vp, s)
                if d is None or d >= limit or vp.view_height * s > 5000:
                    continue
                cands.append(vp)
        if cands:
            break
    if not cands:
        return None
    # group windows by rounded centre (25 m); prefer the group appearing most often, then larger windows
    groups = defaultdict(list)
    g = 25 / s
    for vp in cands:
        groups[(round(vp.model_center[0] / g), round(vp.model_center[1] / g))].append(vp)
    # a window must actually show the drawing (sheets with a logo or an empty corner do not count)
    pts = [f.geom.representative_point() for f in drawing.features if f.kind != "text" and not f.nested]
    step = max(1, len(pts) // 20000)
    sample = points(np.array([(q.x, q.y) for q in pts[::step]])) if pts else None
    best = poly = None
    for grp in sorted(groups.values(), key=lambda g: (len(g), max(v.view_height for v in g)), reverse=True):
        cand = unary_union([viewport_polygon(v.model_center, v.view_width, v.view_height, v.twist_deg) for v in grp])
        if sample is None:
            break
        inside = int(np.count_nonzero(cand.contains(sample)))
        if inside >= max(10, 0.03 * len(sample)):
            best, poly = grp, cand
            break
    if best is None:
        return None
    vp = max(best, key=lambda v: v.view_height * v.view_width)
    return {
        "id": "site",
        "polygon": poly,
        "twist_deg": vp.twist_deg,
        "center": vp.model_center,
        "sheets": sorted({v.layout for v in best}),
        "viewports": [v.handle for v in best],
    }
