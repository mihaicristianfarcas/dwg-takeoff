"""Deterministic measurements on extracted features.

All functions return both the value and the evidence needed to verify it: which entities were
used, how much each one contributed after de-duplication, and the geometry to highlight.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from itertools import pairwise

from shapely import STRtree
from shapely.geometry import LineString, MultiLineString, MultiPolygon, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import linemerge, nearest_points, polygonize, unary_union

from ..cad.model import Feature

AREA_KINDS = ("hatch", "solid", "closed")


@dataclass
class Contribution:
    fid: int | None
    raw: float  # value of this entity on its own
    counted: float  # value actually added to the total after de-duplication
    note: str = ""


@dataclass
class Measurement:
    value: float  # in drawing units (area: units², length: units)
    raw_sum: float
    contributions: list[Contribution]
    geometry: BaseGeometry | None = None  # union geometry (areas) / kept lines
    removed: BaseGeometry | None = None  # discarded duplicate line pieces
    stats: dict = field(default_factory=dict)


# --------------------------------------------------------------------------------------------
# areas
# --------------------------------------------------------------------------------------------


def _safe_union(geoms) -> BaseGeometry:
    try:
        return unary_union(geoms)
    except Exception:
        return unary_union([g.buffer(0) for g in geoms])


def measure_area(features: list[Feature], subtract: list[Feature] | None = None) -> Measurement:
    """Union area of polygonal features. Overlapping or duplicated entities are counted once;
    each entity's `counted` value is the area it adds to the entities processed before it
    (largest first). Only spatial neighbours are compared, so large layers stay fast."""
    polys = [(f, f.geom) for f in features if f.kind in AREA_KINDS and not f.geom.is_empty]
    polys.sort(key=lambda x: -x[1].area)
    geoms = [g for _, g in polys]
    tree = STRtree(geoms) if geoms else None
    contributions = []
    for i, (f, g) in enumerate(polys):
        prev = [int(j) for j in tree.query(g) if j < i]
        covered = 0.0
        if prev:
            try:
                covered = g.intersection(_safe_union([geoms[j] for j in prev])).area
            except Exception:
                covered = g.buffer(0).intersection(_safe_union([geoms[j] for j in prev])).area
        added = max(0.0, g.area - covered)
        note = ""
        if g.area > 0 and added < 0.01 * g.area:
            note = "dublură / acoperit complet de o entitate deja numărată"
        elif g.area > 0 and added < 0.99 * g.area:
            note = f"suprapus parțial ({100 * (1 - added / g.area):.0f}% deja numărat)"
        contributions.append(Contribution(f.fid, g.area, added, note))
    union: BaseGeometry = _safe_union(geoms) if geoms else Polygon()
    raw = sum(c.raw for c in contributions)
    stats = {"entities": len(contributions), "raw_sum": raw, "union": union.area}
    if subtract:
        sub = _safe_union([f.geom for f in subtract if f.kind in AREA_KINDS])
        removed_area = union.intersection(sub).area
        union = union.difference(sub)
        contributions.append(Contribution(None, -removed_area, -removed_area, "suprafață scăzută"))
        stats["subtracted"] = removed_area
    return Measurement(union.area, raw, contributions, union, None, stats)


def measure_perimeter(features: list[Feature]) -> Measurement:
    """Perimeter (outer + inner boundaries) of the union of polygonal features. Entities that
    duplicate an already counted surface contribute nothing; shared edges between touching
    entities are counted once (the union's boundary)."""
    m = measure_area(features)
    union = m.geometry
    total = union.boundary.length if union is not None and not union.is_empty else 0.0
    lookup = {f.fid: f for f in features}
    contributions = []
    for c in m.contributions:
        f = lookup[c.fid]
        per = f.geom.boundary.length
        dup = c.note.startswith("dublură")
        contributions.append(Contribution(c.fid, per, 0.0 if dup else per, c.note))
    counted_sum = sum(c.counted for c in contributions)
    if contributions and abs(counted_sum - total) > 0.01:
        contributions.append(
            Contribution(None, 0.0, total - counted_sum, "corecție: laturi comune / suprapuneri între contururi")
        )
    raw = sum(c.raw for c in contributions)
    return Measurement(total, raw, contributions, union, None, {"raw_sum": raw, "union": total, "union_area": m.value})


# --------------------------------------------------------------------------------------------
# lengths with overlap removal
# --------------------------------------------------------------------------------------------

Coords = list[tuple[float, float]]
Seg = tuple[float, float, float, float]


def _as_lines(f: Feature) -> list[Coords]:
    """Coordinate lists of the linear parts of a feature (outlines for surfaces)."""
    g = f.geom
    if f.kind in AREA_KINDS:
        polys = list(g.geoms) if isinstance(g, MultiPolygon) else [g]
        out = []
        for p in polys:
            if p.is_empty:
                continue
            out.append(list(p.exterior.coords))
            out.extend(list(r.coords) for r in p.interiors)
        return out
    if isinstance(g, LineString):
        return [list(g.coords)]
    if isinstance(g, MultiLineString):
        return [list(x.coords) for x in g.geoms]
    return []


def _length(coords: Coords) -> float:
    return sum(math.dist(a, b) for a, b in pairwise(coords))


def _pieces(coords: Coords, max_len: float) -> list[Seg]:
    """Split a polyline into straight pieces no longer than `max_len`."""
    out = []
    for a, b in pairwise(coords):
        L = math.dist(a, b)
        if L <= 0:
            continue
        n = max(1, math.ceil(L / max_len))
        dx, dy = (b[0] - a[0]) / n, (b[1] - a[1]) / n
        for i in range(n):
            out.append((a[0] + dx * i, a[1] + dy * i, a[0] + dx * (i + 1), a[1] + dy * (i + 1)))
    return out


def _dir(s: Seg) -> tuple[float, float]:
    x0, y0, x1, y1 = s
    L = math.hypot(x1 - x0, y1 - y0) or 1.0
    return (x1 - x0) / L, (y1 - y0) / L


class _SegmentGrid:
    """Incremental spatial hash of line pieces (no rebuilds while pieces are added)."""

    def __init__(self, cell: float):
        self.cell = cell
        self.cells: dict[tuple[int, int], list[int]] = {}
        self.segs: list[Seg] = []
        self.dirs: list[tuple[float, float]] = []

    def add(self, s: Seg, d: tuple[float, float]) -> None:
        x0, y0, x1, y1 = s
        i = len(self.segs)
        self.segs.append(s)
        self.dirs.append(d)
        c = self.cell
        for gx in range(math.floor(min(x0, x1) / c), math.floor(max(x0, x1) / c) + 1):
            for gy in range(math.floor(min(y0, y1) / c), math.floor(max(y0, y1) / c) + 1):
                self.cells.setdefault((gx, gy), []).append(i)

    def near(self, x: float, y: float, r: float):
        c = self.cell
        seen = set()
        for gx in range(math.floor((x - r) / c), math.floor((x + r) / c) + 1):
            for gy in range(math.floor((y - r) / c), math.floor((y + r) / c) + 1):
                for i in self.cells.get((gx, gy), ()):
                    if i not in seen:
                        seen.add(i)
                        yield i


def _point_seg_dist(px, py, x0, y0, x1, y1) -> float:
    dx, dy = x1 - x0, y1 - y0
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / L2))
    return math.hypot(px - (x0 + t * dx), py - (y0 + t * dy))


def _segs_geom(segs: list[Seg]):
    if not segs:
        return LineString()
    return linemerge(MultiLineString([((a, b), (c, d)) for a, b, c, d in segs]))


def measure_length(
    features: list[Feature],
    tolerance: float = 0.3,
    piece: float | None = None,
    max_angle_deg: float = 20.0,
    exclude: list[Feature] | None = None,
    geometry: bool = True,
) -> Measurement:
    """Total length of linear features where a piece of line lying within `tolerance` of, and
    parallel to, an already counted line is treated as the same physical element.

    This removes exact duplicates (the same curb drawn twice) and double-drawn faces of the same
    element (e.g. both edges of a 20 cm curb) while keeping perpendicular joins. Features are
    processed longest first, so the longest drawn representation is the one counted.
    `tolerance` and `piece` are in drawing units (piece defaults to 2 × tolerance).
    `exclude`: lines already counted elsewhere (e.g. by another curb type); pieces of `features`
    running along them are not counted here. `geometry=False` skips building the counted / removed
    traces (callers that only need the numbers).
    """
    if piece is None:
        piece = 2 * tolerance if tolerance > 0 else 1.0
    items = []
    for f in features:
        for coords in _as_lines(f):
            L = _length(coords)
            if L > 0:
                items.append((f, coords, L))
    items.sort(key=lambda x: -x[2])
    cos_max = math.cos(math.radians(max_angle_deg))
    grid = _SegmentGrid(max(tolerance, piece, 1e-9))
    kept: list[Seg] = []
    removed: list[Seg] = []
    per_fid: dict[int, list[float]] = {}
    n_dup_exact = n_dup_parallel = 0.0
    exact_eps = tolerance * 0.07 if tolerance > 0 else 0.0
    n_excluded = 0.0
    excluded_ids = set()
    for xf in exclude or []:
        for coords in _as_lines(xf):
            for sg in _pieces(coords, piece):
                grid.add(sg, _dir(sg))
    n_seed = len(grid.segs)
    segs, dirs = grid.segs, grid.dirs
    for f, coords, L in items:
        new = []
        kept_len = 0.0
        for sg in _pieces(coords, piece):
            x0, y0, x1, y1 = sg
            mx, my = (x0 + x1) / 2, (y0 + y1) / 2
            seg_len = math.hypot(x1 - x0, y1 - y0)
            d = ((x1 - x0) / seg_len, (y1 - y0) / seg_len) if seg_len else (1.0, 0.0)
            dup_dist = None
            by_excluded = False
            if tolerance > 0:
                for i in grid.near(mx, my, tolerance):
                    sx0, sy0, sx1, sy1 = segs[i]
                    dist = _point_seg_dist(mx, my, sx0, sy0, sx1, sy1)
                    if dist <= tolerance:
                        ad = dirs[i]
                        if abs(d[0] * ad[0] + d[1] * ad[1]) >= cos_max:
                            dup_dist = dist if dup_dist is None else min(dup_dist, dist)
                            by_excluded = by_excluded or i < n_seed
            if dup_dist is None:
                kept_len += seg_len
                new.append((sg, d))
                kept.append(sg)
            elif by_excluded:
                removed.append(sg)
                n_excluded += seg_len
                excluded_ids.add(f.fid)
            else:
                removed.append(sg)
                if dup_dist <= exact_eps:
                    n_dup_exact += seg_len
                else:
                    n_dup_parallel += seg_len
        for sg, d in new:  # a feature never de-duplicates against itself
            grid.add(sg, d)
        r = per_fid.setdefault(f.fid, [0.0, 0.0])
        r[0] += L
        r[1] += kept_len
    contributions = []
    for fid, (raw, counted) in per_fid.items():
        note = ""
        if raw > 0 and counted < 0.02 * raw:
            note = "dublură a unei linii deja numărate (suprapusă sau paralelă în toleranță)"
        elif raw > 0 and counted < 0.98 * raw:
            note = f"{raw - counted:.2f} m suprapuși/paraleli nu au fost renumărați"
        if fid in excluded_ids:
            note += ("; " if note else "") + "include traseu numărat deja la alt element (exclus)"
        contributions.append(Contribution(fid, raw, counted, note))
    contributions.sort(key=lambda c: -c.raw)
    total = sum(c.counted for c in contributions)
    raw_sum = sum(c.raw for c in contributions)
    stats = {
        "raw_sum": raw_sum,
        "counted": total,
        "coincident_removed": n_dup_exact,
        "parallel_faces_removed": n_dup_parallel,
        "tolerance": tolerance,
    }
    if exclude:
        stats["excluded_shared"] = n_excluded
    if not geometry:
        return Measurement(total, raw_sum, contributions, None, None, stats)
    return Measurement(total, raw_sum, contributions, _segs_geom(kept), _segs_geom(removed), stats)


def _gap_connectors(lines: list[LineString], snap: float) -> list[LineString]:
    """Short segments closing the gaps at free line ends: from each open end to the nearest other
    line (or to the line's own other end) within `snap`. Only the gaps are bridged; the drawn
    geometry is not moved (snapping a whole network to itself distorts detailed drawings and can
    exhaust memory)."""
    tree = STRtree(lines)
    out = []
    for i, ln in enumerate(lines):
        if ln.is_closed:
            continue
        ends = (Point(ln.coords[0]), Point(ln.coords[-1]))
        if 0 < ends[0].distance(ends[1]) <= snap:
            out.append(LineString(ends))
        for pt in ends:
            best = None
            for j in tree.query(pt, predicate="dwithin", distance=snap):
                if j != i:
                    d = lines[j].distance(pt)
                    if best is None or d < best[0]:
                        best = (d, int(j))
            if best is not None and best[0] > 0:
                out.append(LineString([pt, nearest_points(pt, lines[best[1]])[1]]))
    return out


def measure_enclosed_area(features: list[Feature], snap: float = 0.0) -> Measurement:
    """Area enclosed by lines that close into loops - e.g. a property boundary or a parking
    outline drawn as separate segments rather than one closed polyline. Gaps at line ends up to
    `snap` (drawing units) are bridged first. Each feature's `counted` value is the length of it
    that lies on the outline of the enclosed area."""
    lines = [LineString(c) for f in features for c in _as_lines(f) if len(c) >= 2]
    if not lines:
        return Measurement(
            0.0, 0.0, [], Polygon(), None, {"faces": 0, "lines": 0, "outline_length": 0.0, "raw_sum": 0.0}
        )
    net = unary_union(lines + (_gap_connectors(lines, snap) if snap > 0 else []))  # nodes crossings
    faces = list(polygonize(net))
    area = _safe_union(faces) if faces else Polygon()
    outline = area.boundary if not area.is_empty else LineString()
    near = outline.buffer(max(snap, 1e-6) * 2) if not area.is_empty else None
    contributions = []
    for f in features:
        L = sum(_length(c) for c in _as_lines(f))
        on = (
            f.geom.intersection(near).length
            if near is not None and f.kind not in AREA_KINDS
            else (f.geom.boundary.intersection(near).length if near is not None else 0.0)
        )
        note = (
            "pe conturul suprafeței închise"
            if on > 0.5 * L
            else ("parțial pe contur" if on > 0 else "nu închide nicio suprafață (linie liberă)")
        )
        contributions.append(Contribution(f.fid, L, min(on, L), note))
    stats = {
        "faces": len(faces),
        "lines": len(lines),
        "outline_length": outline.length,
        "raw_sum": sum(c.raw for c in contributions),
    }
    return Measurement(area.area, stats["raw_sum"], contributions, area, None, stats)


def measure_groups(features: list[Feature], join: float, min_size: float = 0.0) -> Measurement:
    """Count symbols drawn without blocks (a stair drawn as lines, a lamp drawn as a circle and a
    cross): geometry closer than `join` (drawing units) belongs to the same group. Groups whose
    extent is below `min_size` are ignored. `geometry` holds one envelope per group."""
    geoms = [(f, f.geom) for f in features if f.kind != "text" and not f.geom.is_empty]
    if not geoms:
        return Measurement(0, 0, [], Polygon(), None, {"groups": 0, "entities": 0, "join": join})
    tree = STRtree([g for _, g in geoms])
    parent = list(range(len(geoms)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    left, right = tree.query([g for _, g in geoms], predicate="dwithin", distance=join)
    for a, b in zip(left, right, strict=True):
        ra, rb = find(int(a)), find(int(b))
        if ra != rb:
            parent[ra] = rb
    groups: dict[int, list[int]] = {}
    for i in range(len(geoms)):
        groups.setdefault(find(i), []).append(i)
    envs, contributions, small = [], [], 0
    for members in sorted(groups.values(), key=lambda m: min(geoms[i][0].fid for i in m)):
        env = unary_union([geoms[i][1] for i in members]).envelope
        x0, y0, x1, y1 = env.bounds
        if max(x1 - x0, y1 - y0) < min_size:
            small += 1
            continue
        envs.append(env)
        first = geoms[members[0]][0]
        contributions.append(
            Contribution(first.fid, 1, 1, f"grup de {len(members)} entități, {x1 - x0:.3g} × {y1 - y0:.3g}")
        )
    return Measurement(
        len(envs),
        len(groups),
        contributions,
        unary_union(envs) if envs else Polygon(),
        None,
        {"groups": len(envs), "entities": len(geoms), "join": join, "ignored_small": small, "envelopes": envs},
    )


def measure_strip_area(features: list[Feature]) -> Measurement:
    """Painted/drawn area of polylines that have a constant width (e.g. road-marking stripes):
    centre-line length × width, overlaps between stripes counted once."""
    wide = [f for f in features if f.width and f.kind in ("line", "closed")]
    strips = []
    for f in wide:
        g = f.geom.boundary if f.kind == "closed" else f.geom
        strips.append((f, g.buffer(f.width / 2, cap_style="flat", join_style="mitre")))
    union: BaseGeometry = Polygon()
    contributions = []
    for f, g in sorted(strips, key=lambda x: -x[1].area):
        before = union.area
        union = union.union(g)
        added = union.area - before
        note = f"lățime {f.width:g} × lungime {f.length:.2f}"
        if g.area > 0 and added < 0.99 * g.area:
            note += f"; {100 * (1 - added / g.area):.0f}% suprapus cu alte benzi"
        contributions.append(Contribution(f.fid, g.area, added, note))
    raw = sum(c.raw for c in contributions)
    return Measurement(
        union.area,
        raw,
        contributions,
        union,
        None,
        {
            "raw_sum": raw,
            "union": union.area,
            "entities": len(contributions),
            "ignored_without_width": len(features) - len(wide),
        },
    )


# --------------------------------------------------------------------------------------------
# counts
# --------------------------------------------------------------------------------------------


def measure_count(features: list[Feature]) -> Measurement:
    seen = {}
    contributions = []
    for f in features:
        key = (f.kind, f.block, round(f.geom.centroid.x, 2), round(f.geom.centroid.y, 2))
        if key in seen:
            contributions.append(Contribution(f.fid, 1, 0, "dublură în aceeași poziție"))
            continue
        seen[key] = f.fid
        contributions.append(Contribution(f.fid, 1, 1))
    total = sum(c.counted for c in contributions)
    pts = unary_union([f.geom.centroid for f in features]) if features else Point()
    return Measurement(total, len(features), contributions, pts, None, {"raw_count": len(features)})
