"""The plan image behind the viewer: one background rendering of the site region (or of the bulk
of the drawing) plus sharper tiles for deep zoom, rendered in worker processes and cached in the
project folder."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path

import numpy as np

from ..cad import convert
from ..cad.render import feature_bounds, render_region, render_tile
from ..store import PIPELINE_VERSION, STORE, Project, worker_pool

TILE_LEVELS = 5  # level z splits the background window in 2^z × 2^z tiles of 1024 px
_RENDER_LOCKS: dict[str, threading.Lock] = {}
_HANDLE_BOUNDS: dict[str, dict] = {}


def view_paths(p: Project) -> tuple[Path, Path]:
    return p.cache_dir / f"view-v{PIPELINE_VERSION}.png", p.cache_dir / f"view-v{PIPELINE_VERSION}.json"


def view_bounds(p: Project) -> tuple[float, float, float, float]:
    """Model rectangle shown by the viewer: the site region, else the bulk of the drawing (stray
    entities far away from the plan are left out)."""
    if p.focus:
        b = p.focus["polygon"].bounds
    else:
        feats = p.drawing.features
        step = max(1, len(feats) // 50000)
        xs = [f.geom.bounds for f in feats[::step] if not f.geom.is_empty]
        if not xs:
            return (0.0, 0.0, 10 / p.drawing.unit_scale, 10 / p.drawing.unit_scale)
        arr = np.array(xs, dtype=float)
        b = (
            float(np.percentile(arr[:, 0], 2)),
            float(np.percentile(arr[:, 1], 2)),
            float(np.percentile(arr[:, 2], 98)),
            float(np.percentile(arr[:, 3], 98)),
        )
    size = max(b[2] - b[0], b[3] - b[1])
    if size <= 0:
        size = 10 / p.drawing.unit_scale  # a single point or text: show 10 m around it
    pad = 0.08 * size
    cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    hw, hh = max(b[2] - b[0], size * 0.05) / 2 + pad, max(b[3] - b[1], size * 0.05) / 2 + pad
    return (cx - hw, cy - hh, cx + hw, cy + hh)


def same_bounds(a, b) -> bool:
    size = max(abs(a[2] - a[0]), abs(a[3] - a[1]), 1e-9)
    return all(abs(x - y) <= 1e-6 * size for x, y in zip(a, b, strict=True))


def _run(fn, *args):
    """Rendering is CPU-bound pure Python: in a worker process when the server uses them."""
    return worker_pool().submit(fn, *args).result() if STORE.use_processes else fn(*args)


def cached_view(p: Project) -> dict | None:
    """The rendered background, if it shows the current window (units and site region unchanged)."""
    png, meta = view_paths(p)
    if png.exists() and meta.exists():
        m = json.loads(meta.read_text())
        if same_bounds(m["bounds"], view_bounds(p)):
            return m
    return None


def ensure_view(p: Project) -> dict:
    """Render the background image unless a current one exists."""
    if (m := cached_view(p)) is not None:
        return m
    with _RENDER_LOCKS.setdefault(p.id, threading.Lock()):
        if (m := cached_view(p)) is not None:
            return m
        png, meta = view_paths(p)
        for old in list(p.cache_dir.glob("view*.png")) + list(p.cache_dir.glob("view*.json")):
            if old.name not in (png.name, meta.name):
                old.unlink(missing_ok=True)  # rendered by an older pipeline version
        t = time.time()
        m = _run(
            render_region,
            str(convert.to_dxf(p.source_path)),
            view_bounds(p),
            png,
            5000,
            None,
            p.drawing.space,
            feature_bounds(p.drawing.features),
        )
        p.timings["render_s"] = round(time.time() - t, 1)
        return m


def ensure_view_in_background(p: Project) -> None:
    threading.Thread(target=ensure_view, args=(p,), daemon=True).start()


def tile_path(p: Project, z: int, i: int, j: int) -> Path:
    """A rendered tile (z: zoom level 1..TILE_LEVELS; i, j: column from the left, row from the
    bottom of the background window), rendered on first use."""
    n = 2**z
    x0, y0, x1, y1 = view_bounds(p)
    tw, th = (x1 - x0) / n, (y1 - y0) / n
    key = hashlib.sha1(repr([round(v, 6) for v in (x0, y0, x1, y1)]).encode()).hexdigest()[:10]
    out = p.cache_dir / f"tiles-v{PIPELINE_VERSION}-{key}" / f"{z}_{i}_{j}.png"
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        if p.id not in _HANDLE_BOUNDS:
            _HANDLE_BOUNDS[p.id] = feature_bounds(p.drawing.features)
        b = (x0 + i * tw, y0 + j * th, x0 + (i + 1) * tw, y0 + (j + 1) * th)
        _run(render_tile, str(convert.to_dxf(p.source_path)), b, out, p.drawing.space, _HANDLE_BOUNDS[p.id])
    return out
