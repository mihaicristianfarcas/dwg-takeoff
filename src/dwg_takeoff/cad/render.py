"""Background image of the plan (CAD-faithful rendering via ezdxf) for the web viewer.

The image covers an exact model-space rectangle so the viewer can draw highlight overlays in
model coordinates on top of it.
"""

from __future__ import annotations

import json
import threading
from collections import defaultdict
from pathlib import Path

from ezdxf import bbox as ezbbox
from ezdxf.addons.drawing import Frontend, RenderContext
from ezdxf.addons.drawing.config import BackgroundPolicy, Configuration, LineweightPolicy
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.collections import LineCollection
from matplotlib.figure import Figure

from .entities import load_doc

_LOCK = threading.Lock()  # matplotlib/ezdxf rendering is not thread-safe


class _BatchedBackend(MatplotlibBackend):
    """Matplotlib backend that draws consecutive lines and polylines as one collection per
    colour/width instead of one artist each (a site plan has 100k+ of them). Batches are flushed
    before every fill, so the drawing order of fills and lines is preserved."""

    def __init__(self, ax, flatten: float, **kw):
        super().__init__(ax, **kw)
        self._flatten = flatten
        self._batch: dict[tuple, list] = defaultdict(list)

    def _flush(self):
        for (color, lw), segs in self._batch.items():
            self.ax.add_collection(
                LineCollection(segs, linewidths=lw, color=color, zorder=self._get_z(), capstyle="butt")
            )
        self._batch.clear()

    def draw_line(self, start, end, properties):
        if start.isclose(end):
            self._flush()
            return super().draw_line(start, end, properties)
        self._batch[(properties.color, self.get_lineweight(properties))].append(((start.x, start.y), (end.x, end.y)))

    def draw_solid_lines(self, lines, properties):
        key = (properties.color, self.get_lineweight(properties))
        for s, e in lines:
            if not s.isclose(e):
                self._batch[key].append(((s.x, s.y), (e.x, e.y)))

    def draw_path(self, path, properties):
        try:
            pts = [(v.x, v.y) for v in path.flattening(self._flatten)]
        except Exception:
            self._flush()
            return super().draw_path(path, properties)
        if len(pts) >= 2:
            self._batch[(properties.color, self.get_lineweight(properties))].append(pts)

    def draw_point(self, pos, properties):
        self._flush()
        super().draw_point(pos, properties)

    def draw_filled_paths(self, paths, properties):
        self._flush()
        super().draw_filled_paths(paths, properties)

    def draw_filled_polygon(self, points, properties):
        self._flush()
        super().draw_filled_polygon(points, properties)

    def draw_image(self, image_data, properties):
        self._flush()
        super().draw_image(image_data, properties)

    def finalize(self):
        self._flush()
        super().finalize()


def render_region(
    dxf_path: str,
    bounds: tuple[float, float, float, float],
    out_png: Path,
    max_px: int = 5000,
    doc=None,
    layout: str = "Model",
    handle_bounds: dict[str, tuple[float, float, float, float]] | None = None,
) -> dict:
    """Render the window `bounds` of `layout` to `out_png`. `handle_bounds` (extents of the
    top-level entities, from the extraction) avoids exploding every block just to know whether
    it lies in the window."""
    doc = doc or load_doc(dxf_path)
    msp = doc.modelspace() if layout in (None, "Model") else doc.layouts.get(layout)
    xmin, ymin, xmax, ymax = bounds
    w, h = xmax - xmin, ymax - ymin
    cache = ezbbox.Cache()

    def huge(b) -> bool:  # entities that only frame the area (survey grids, background fills)
        return b[2] - b[0] > 20 * w and b[3] - b[1] > 20 * h

    def inside(b) -> bool:
        x0, y0, x1, y1 = b
        return not (x1 < xmin or x0 > xmax or y1 < ymin or y0 > ymax)

    def keep(e) -> bool:
        if handle_bounds is not None:
            hb = handle_bounds.get(e.dxf.handle)
            if hb is not None and not huge(hb):
                return inside(hb)
        try:
            b = ezbbox.extents([e], fast=True, cache=cache)
        except Exception:
            return False
        if not b.has_data:
            return False
        bb = (b.extmin.x, b.extmin.y, b.extmax.x, b.extmax.y)
        return not huge(bb) and inside(bb)

    dpi = 100
    scale = max_px / max(w, h)
    px = 1 / scale  # one output pixel in drawing units
    with _LOCK:
        _draw(doc, msp, keep, (xmin, ymin, xmax, ymax), w * scale / dpi, h * scale / dpi, dpi, out_png, px)
    meta = {"bounds": [xmin, ymin, xmax, ymax], "px": [round(w * scale), round(h * scale)]}
    tmp = out_png.with_name(out_png.stem + ".json.tmp")
    tmp.write_text(json.dumps(meta))
    tmp.replace(out_png.with_suffix(".json"))
    return meta


_DOCS: dict[str, object] = {}  # parsed DXF per worker process (tiles of one drawing reuse it)


def render_tile(dxf_path: str, bounds, out_png: Path, layout: str, handle_bounds, px: int = 1024) -> dict:
    """A high-resolution piece of the plan for deep zoom (same rendering as the background)."""
    doc = _DOCS.get(dxf_path)
    if doc is None:
        _DOCS.clear()  # keep one drawing in memory per worker
        doc = _DOCS[dxf_path] = load_doc(dxf_path)
    return render_region(dxf_path, bounds, out_png, max_px=px, doc=doc, layout=layout, handle_bounds=handle_bounds)


def feature_bounds(features) -> dict[str, tuple[float, float, float, float]]:
    """Extents per top-level handle (an INSERT covers all geometry exploded from it). Texts are
    stored as their insertion point, so they count with a generous box around it."""
    out: dict[str, list[float]] = {}
    texts = {f.handle for f in features if f.kind == "text" and not f.nested}
    for f in features:
        if f.geom.is_empty or f.handle in texts or (f.kind == "block" and f.nested):
            continue  # top-level texts: real extents measured by ezdxf; nested insertion points are not drawn
        b = f.geom.bounds
        if f.kind == "text":
            r = (f.text_height or 0) * (len(f.text or "") + 1)
            b = (b[0] - r, b[1] - r, b[2] + r, b[3] + r)
        cur = out.get(f.handle)
        if cur is None:
            out[f.handle] = list(b)
        else:
            cur[0], cur[1], cur[2], cur[3] = min(cur[0], b[0]), min(cur[1], b[1]), max(cur[2], b[2]), max(cur[3], b[3])
    return {k: tuple(v) for k, v in out.items()}


def _draw(doc, msp, keep, bounds, fig_w, fig_h, dpi, out_png, px):
    xmin, ymin, xmax, ymax = bounds
    fig = Figure(figsize=(fig_w, fig_h), dpi=dpi)
    FigureCanvasAgg(fig)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()
    ctx = RenderContext(doc)
    # detail finer than a pixel is approximated: dense hatch patterns become a solid tint and
    # tiny dashes solid lines, otherwise a city-scale plan can produce millions of segments
    cfg = Configuration(
        background_policy=BackgroundPolicy.WHITE,
        lineweight_policy=LineweightPolicy.RELATIVE,
        lineweight_scaling=0.6,
        min_hatch_line_distance=1.5 * px,
        min_dash_length=px,
        max_flattening_distance=0.5 * px,
        hatching_timeout=5.0,
    )
    backend = _BatchedBackend(ax, 0.5 * px, adjust_figure=False)
    Frontend(ctx, backend, config=cfg).draw_layout(msp, finalize=True, filter_func=keep)
    ax.set_xlim(xmin, xmax)
    ax.set_ylim(ymin, ymax)
    ax.set_aspect("auto")
    tmp = out_png.with_name(out_png.stem + ".tmp.png")
    fig.savefig(tmp, dpi=dpi, facecolor="white")
    tmp.replace(out_png)
