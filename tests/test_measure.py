"""Unit tests for the measurement rules on synthetic geometry."""

import math

import pytest
from shapely.geometry import LineString, Point, Polygon

from dwg_takeoff.cad import Feature
from dwg_takeoff.cad.georef import TableTransform
from dwg_takeoff.cad.tables import table_polygon
from dwg_takeoff.engine.measure import measure_area, measure_count, measure_length, measure_perimeter


def feat(fid, geom, kind, layer="L", block=None):
    return Feature(fid=fid, handle=f"H{fid}", layer=layer, dxftype="X", kind=kind, geom=geom, block=block)


def rect(x0, y0, x1, y1):
    return Polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


def test_area_duplicates_counted_once():
    a = feat(0, rect(0, 0, 10, 10), "hatch")
    dup = feat(1, rect(0, 0, 10, 10), "hatch", layer="copy")
    m = measure_area([a, dup])
    assert m.value == pytest.approx(100)
    assert m.raw_sum == pytest.approx(200)
    counted = sorted(c.counted for c in m.contributions)
    assert counted == pytest.approx([0, 100])


def test_area_partial_overlap_and_subtract():
    a = feat(0, rect(0, 0, 10, 10), "hatch")
    b = feat(1, rect(5, 0, 15, 10), "hatch")
    m = measure_area([a, b])
    assert m.value == pytest.approx(150)
    hole = feat(2, rect(0, 0, 2, 2), "closed")
    m2 = measure_area([a, b], subtract=[hole])
    assert m2.value == pytest.approx(146)


def test_length_removes_coincident_and_parallel_faces():
    main = feat(0, LineString([(0, 0), (100, 0)]), "line")
    copy = feat(1, LineString([(0, 0), (100, 0)]), "line")  # same curb drawn twice
    face = feat(2, LineString([(0, 0.2), (100, 0.2)]), "line")  # other face of a 20 cm curb
    other = feat(3, LineString([(0, 5), (50, 5)]), "line")  # a different curb 5 m away
    m = measure_length([main, copy, face, other], tolerance=0.3)
    assert m.value == pytest.approx(150, abs=0.01)
    assert m.raw_sum == pytest.approx(350)
    assert m.stats["coincident_removed"] == pytest.approx(100, abs=0.01)
    assert m.stats["parallel_faces_removed"] == pytest.approx(100, abs=0.01)


def test_length_keeps_perpendicular_joins():
    a = feat(0, LineString([(0, 0), (10, 0)]), "line")
    b = feat(1, LineString([(10, 0), (10, 10)]), "line")  # meets `a` at a right angle
    m = measure_length([a, b], tolerance=0.3)
    assert m.value == pytest.approx(20, abs=0.01)


def test_length_of_closed_outline_uses_perimeter():
    island = feat(0, rect(0, 0, 4, 1), "closed")
    m = measure_length([island], tolerance=0.3)
    assert m.value == pytest.approx(10)


def test_perimeter_of_touching_footprints():
    a = feat(0, rect(0, 0, 2, 2), "closed")
    b = feat(1, rect(2, 0, 4, 2), "closed")  # shares one edge with `a`
    m = measure_perimeter([a, b])
    assert m.value == pytest.approx(12)
    assert sum(c.counted for c in m.contributions) == pytest.approx(12)


def test_count_ignores_stacked_duplicates():
    f = [
        feat(0, Point(0, 0), "block", block="Stalp"),
        feat(1, Point(0, 0), "block", block="Stalp"),
        feat(2, Point(5, 0), "block", block="Stalp"),
    ]
    assert measure_count(f).value == 2


def test_table_polygon_ignores_centre_point():
    pts = [("M1.1", 0.0, 0.0), ("M1.2", 0.0, 3.2), ("M1.3", 3.2, 3.2), ("M1.4", 3.2, 0.0), ("M1.C", 1.6, 1.6)]
    p = table_polygon(pts)
    assert p.area == pytest.approx(10.24)
    assert p.length == pytest.approx(12.8)


def test_table_transform_swap_and_rotation():
    tr = TableTransform(
        a=math.cos(math.pi / 2),
        b=math.sin(math.pi / 2),
        tx=10,
        ty=0,
        matched=4,
        total=4,
        rms=0,
        matched_points=[],
        swap_xy=True,
    )
    # (E, N) = (1, 2) -> swapped (2, 1) -> rotated 90° -> (-1, 2) -> +10 in x
    x, y = tr.apply(1, 2)
    assert (x, y) == pytest.approx((9, 2))


def test_strip_area_uses_polyline_width():
    from dwg_takeoff.engine.measure import measure_strip_area

    stripe = Feature(
        fid=0,
        handle="H0",
        layer="marcaje",
        dxftype="LWPOLYLINE",
        kind="line",
        geom=LineString([(0, 0), (5, 0)]),
        width=0.2,
    )
    thin = feat(1, LineString([(0, 1), (5, 1)]), "line")
    m = measure_strip_area([stripe, thin])
    assert m.value == pytest.approx(1.0)
    assert m.stats["ignored_without_width"] == 1


def test_length_in_millimetre_drawing_is_fast_and_correct():
    import time

    # 40 m curb drawn twice + both faces of a 10 x 5 m island, coordinates in mm
    a = feat(0, LineString([(0, 20000), (40000, 20000)]), "line")
    b = feat(1, LineString([(0, 20000), (40000, 20000)]), "line")
    outer = feat(2, rect(15000, 7500, 25000, 12500), "closed")
    inner = feat(3, rect(15200, 7700, 24800, 12300), "closed")
    t = time.time()
    m = measure_length([a, b, outer, inner], tolerance=250, piece=500)
    assert time.time() - t < 2
    assert m.value == pytest.approx(70000, rel=1e-3)


def test_length_exclude_shared_trace():
    big = feat(0, LineString([(0, 0), (30, 0)]), "line", layer="20x25")
    small = feat(1, LineString([(20, 0.1), (40, 0.1)]), "line", layer="10x15")  # 10 m shared with `big`
    m = measure_length([small], tolerance=0.25, exclude=[big])
    assert m.value == pytest.approx(10, abs=0.3)
    assert m.stats["excluded_shared"] == pytest.approx(10, abs=0.3)


def test_enclosed_area_bridges_gaps_and_keeps_detail():
    """A 10 x 10 m room drawn as separate walls with a 3 cm gap, next to detail drawn as many short
    parallel lines 10 cm apart: the gap is bridged, the detail stays as drawn and the measurement
    stays fast (snapping the whole network to itself distorted detailed drawings and could exhaust
    memory)."""
    import time

    from dwg_takeoff.engine.measure import measure_enclosed_area

    walls = [((0, 0), (10, 0)), ((10, 0), (10, 10)), ((10, 10), (0, 10)), ((0, 10), (0, 0.03))]
    feats = [feat(i, LineString(w), "line") for i, w in enumerate(walls)]
    feats += [feat(10 + k, LineString([(12, k * 0.1), (20, k * 0.1)]), "line") for k in range(500)]
    t = time.time()
    m = measure_enclosed_area(feats, snap=0.05)
    assert time.time() - t < 5
    assert m.value == pytest.approx(100, rel=1e-3) and m.stats["faces"] == 1
    assert measure_enclosed_area(feats, snap=0.0).value == 0  # without bridging the room stays open
