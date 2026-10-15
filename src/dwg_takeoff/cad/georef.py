"""Align setting-out tables (coordinates in the national system, e.g. Stereo 70: Nord X / Est Y)
with the model space of the drawing.

Setting-out tables list the corners of buildings and foundations. Some of those corners (usually
the building outline) are also drawn in model space, so we look for the rigid/similarity
transform that maps as many table points as possible onto drawn vertices (RANSAC on point pairs
of equal length). With it, footprints that exist only in the tables (pad foundations, totems,
canopies) can be drawn on the plan for verification.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass

import numpy as np
from shapely.geometry import MultiPolygon, Polygon
from shapely.prepared import prep

from .model import Drawing


@dataclass
class TableTransform:
    a: float  # x' = a*x - b*y + tx   (x, y) = (E, N), or (N, E) when swap_xy
    b: float  # y' = b*x + a*y + ty
    tx: float
    ty: float
    matched: int
    total: int
    rms: float
    matched_points: list
    swap_xy: bool = False

    @property
    def scale(self) -> float:
        return math.hypot(self.a, self.b)

    @property
    def rotation_deg(self) -> float:
        return math.degrees(math.atan2(self.b, self.a))

    def apply(self, x: float, y: float) -> tuple[float, float]:
        """Map a table point given as (E, N) to model coordinates."""
        if self.swap_xy:
            x, y = y, x
        return self.a * x - self.b * y + self.tx, self.b * x + self.a * y + self.ty

    def to_dict(self) -> dict:
        return {
            "matched": self.matched,
            "total": self.total,
            "rms_m": self.rms,
            "scale": self.scale,
            "rotation_deg": self.rotation_deg,
            "swap_xy": self.swap_xy,
            "matched_points": self.matched_points,
        }


def _similarity(src: np.ndarray, dst: np.ndarray):
    """Least-squares similarity transform (no reflection) src -> dst."""
    sc, dc = src.mean(0), dst.mean(0)
    s, d = src - sc, dst - dc
    denom = (s**2).sum()
    if denom == 0:
        return None
    a = (s[:, 0] * d[:, 0] + s[:, 1] * d[:, 1]).sum() / denom
    b = (s[:, 0] * d[:, 1] - s[:, 1] * d[:, 0]).sum() / denom
    tx = dc[0] - (a * sc[0] - b * sc[1])
    ty = dc[1] - (b * sc[0] + a * sc[1])
    return a, b, tx, ty


class _Grid:
    def __init__(self, pts: np.ndarray, cell: float):
        self.cell = cell
        self.pts = pts
        self.cells = defaultdict(list)
        for i, (x, y) in enumerate(pts):
            self.cells[(int(x // cell), int(y // cell))].append(i)

    def nearest(self, x: float, y: float, maxd: float):
        cx, cy = int(x // self.cell), int(y // self.cell)
        best, bd = None, maxd
        for i in (cx - 1, cx, cx + 1):
            for j in (cy - 1, cy, cy + 1):
                for k in self.cells.get((i, j), ()):
                    px, py = self.pts[k]
                    d = math.hypot(px - x, py - y)
                    if d <= bd:
                        best, bd = k, d
        return best, bd


def georeference_tables(drawing: Drawing, region=None, tol: float = 0.05) -> TableTransform | None:
    tpts = []
    for t in drawing.tables:
        for obj, pts in t.objects.items():
            for name, n, e in pts:
                tpts.append((f"{obj} / {name}", e, n))
    uniq = {}
    for label, x, y in tpts:
        uniq.setdefault((round(x, 3), round(y, 3)), label)
    if len(uniq) < 3:
        return None
    P0 = np.array(list(uniq.keys()), dtype=float)
    labels = list(uniq.values())
    objs = np.array([lb.split(" / ")[0] for lb in labels])

    pr = prep(region) if region is not None else None
    verts = set()
    for f in drawing.features:
        if f.nested or f.kind not in ("closed", "hatch", "solid"):
            continue
        g = f.geom
        if g.area < 5 / drawing.unit_scale**2:
            continue
        if pr is not None and not pr.contains(g.representative_point()):
            continue
        polys = list(g.geoms) if isinstance(g, MultiPolygon) else [g]
        for p in polys:
            for c in p.exterior.coords:
                verts.add((round(c[0], 4), round(c[1], 4)))
    if len(verts) < 3:
        return None
    V = np.array(sorted(verts), dtype=float)
    if len(V) > 4000:
        V = V[np.random.default_rng(0).choice(len(V), 4000, replace=False)]
    grid = _Grid(V, max(tol * 4, 0.2))

    # model pairwise distances (upper triangle)
    iu, ju = np.triu_indices(len(V), k=1)
    dv = np.hypot(V[iu, 0] - V[ju, 0], V[iu, 1] - V[ju, 1])
    order = np.argsort(dv)
    dv_sorted = dv[order]

    results = []
    for swap in (False, True):
        P = P0[:, ::-1].copy() if swap else P0
        r = _ransac(P, V, grid, order, dv_sorted, iu, ju, tol, objs)
        if r:
            results.append((len(r[1]), -r[2], swap, r))
    if not results:
        return None
    _, _, swap, (_tr, inl, _) = max(results, key=lambda x: (x[0], x[1]))
    if len(inl) < 4:
        return None
    P = P0[:, ::-1].copy() if swap else P0
    src = P[[i for i, _, _ in inl]]
    dst = V[[j for _, j, _ in inl]]
    a, b, tx, ty = _similarity(src, dst)
    X = a * src[:, 0] - b * src[:, 1] + tx
    Y = b * src[:, 0] + a * src[:, 1] + ty
    rms = float(np.sqrt(((X - dst[:, 0]) ** 2 + (Y - dst[:, 1]) ** 2).mean()))
    return TableTransform(a, b, tx, ty, len(inl), len(P), rms, [labels[i] for i, _, _ in inl], swap)


def _ransac(P, V, grid, order, dv_sorted, iu, ju, tol, objs, top_k: int = 60):
    """Hypotheses: a pair of table points matched to a pair of drawn vertices at the same
    distance gives a similarity transform. All hypotheses are scored at once with a coarse
    cell test (numpy); the best `top_k` are scored exactly (inliers within `tol`, error sum)."""
    # seed pairs: points of the same object (corners of one outline are the most likely to be
    # drawn), longest first, plus the longest pairs overall
    ti, tj = np.triu_indices(len(P), k=1)
    dt = np.hypot(P[ti, 0] - P[tj, 0], P[ti, 1] - P[tj, 1])
    same = np.where(objs[ti] == objs[tj])[0]
    same = same[np.argsort(-dt[same])][:80]
    tp = list(dict.fromkeys(list(same) + list(np.argsort(-dt)[:20])))

    sa, sb, da, db = [], [], [], []
    for k in tp:
        d = dt[k]
        if d < 3:
            break
        lo, hi = np.searchsorted(dv_sorted, [d - 0.02, d + 0.02])
        ms = order[lo:hi][:400]
        if not len(ms):
            continue
        for u, v in ((iu[ms], ju[ms]), (ju[ms], iu[ms])):
            sa.append(np.full(len(ms), ti[k]))
            sb.append(np.full(len(ms), tj[k]))
            da.append(u)
            db.append(v)
    if not sa:
        return None
    sa, sb, da, db = (np.concatenate(x) for x in (sa, sb, da, db))
    Pc = P[:, 0] + 1j * P[:, 1]
    Vc = V[:, 0] + 1j * V[:, 1]
    z = (Vc[db] - Vc[da]) / (Pc[sb] - Pc[sa])  # rotation + scale as a complex number (a + ib)
    ok = np.abs(np.abs(z) - 1) <= 0.01  # the tables and the drawing share the same scale
    z, t = z[ok], (Vc[da] - z * Pc[sa])[ok]
    if not len(z):
        return None
    # coarse score: transformed points falling in a cell next to a drawn vertex
    cell = tol
    vx, vy = np.floor(V[:, 0] / cell).astype(np.int64), np.floor(V[:, 1] / cell).astype(np.int64)
    keys = np.unique(np.concatenate([(vx + dx) * 4_294_967_296 + (vy + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)]))
    coarse = np.zeros(len(z), dtype=np.int32)
    for c0 in range(0, len(z), 20000):
        T = z[c0 : c0 + 20000, None] * Pc[None, :] + t[c0 : c0 + 20000, None]
        k = np.floor(T.real / cell).astype(np.int64) * 4_294_967_296 + np.floor(T.imag / cell).astype(np.int64)
        pos = np.clip(np.searchsorted(keys, k), 0, len(keys) - 1)
        coarse[c0 : c0 + 20000] = (keys[pos] == k).sum(axis=1)
    best = None
    for c in np.argsort(-coarse, kind="stable")[:top_k]:
        a, b, tx, ty = z[c].real, z[c].imag, t[c].real, t[c].imag
        X = a * P[:, 0] - b * P[:, 1] + tx
        Y = b * P[:, 0] + a * P[:, 1] + ty
        inl = []
        for i in range(len(P)):
            j, dist = grid.nearest(X[i], Y[i], tol)
            if j is not None:
                inl.append((i, j, dist))
        err = sum(dist for _, _, dist in inl)
        if best is None or len(inl) > len(best[1]) or (len(inl) == len(best[1]) and err < best[2]):
            best = ((a, b, tx, ty), inl, err)
    return best


def transformed_polygon(poly: Polygon, tr: TableTransform) -> Polygon:
    if poly.is_empty:
        return poly
    return Polygon([tr.apply(x, y) for x, y in poly.exterior.coords])
