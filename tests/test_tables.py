"""Setting-out tables: object footprints listed by coordinates, measured and subtracted like drawn
outlines once the tables are georeferenced onto the plan."""

import pytest
from shapely.geometry import Polygon

from dwg_takeoff.cad import Drawing, EmbeddedTable, Feature
from dwg_takeoff.cad.georef import TableTransform
from dwg_takeoff.engine.executor import execute_plan

IDENTITY = TableTransform(a=1, b=0, tx=0, ty=0, matched=4, total=4, rms=0, matched_points=[])


@pytest.fixture()
def site():
    paving = Feature(
        fid=0,
        handle="A1",
        layer="PAVING",
        dxftype="HATCH",
        kind="hatch",
        geom=Polygon([(0, 0), (20, 0), (20, 10), (0, 10)]),
        pattern="SOLID",
    )
    # a 2 x 2 m pylon base that exists only in the table: points are (name, North, East)
    pylon = [("P.1", 1.0, 1.0), ("P.2", 1.0, 3.0), ("P.3", 3.0, 3.0), ("P.4", 3.0, 1.0), ("P.C", 2.0, 2.0)]
    table = EmbeddedTable("T1", ["Plan"], "xlsx", "Pylon", [["Ob", "Pylon"]], {"Pylon": pylon})
    return Drawing("t.dxf", "t.dxf", "AC1032", "meters", 1.0, {}, [paving], [], [], [table], [], [])


def paving_minus_pylon():
    comp = {
        "label": "c",
        "measure": "area",
        "region": None,
        "tolerance_m": None,
        "factors": [],
        "sources": [{"layer": "PAVING", "kinds": ["hatch"]}],
        "subtract_sources": [{"layer": None, "kinds": ["table_polygon"], "table_object": "Pylon"}],
    }
    return {"items": [{"id": "x", "label": "x", "unit": "m²", "components": [comp]}]}


def test_table_footprint_measured(site):
    comp = {
        "label": "c",
        "measure": "area",
        "region": None,
        "tolerance_m": None,
        "factors": [],
        "sources": [{"layer": None, "kinds": ["table_polygon"], "table_object": "pylon"}],
    }
    res = execute_plan({"items": [{"id": "x", "label": "x", "unit": "m²", "components": [comp]}]}, site, {})
    assert res["items"][0]["value"] == pytest.approx(4)  # the centre point P.C is not a corner


def test_georeferenced_footprint_is_subtracted(site):
    res = execute_plan(paving_minus_pylon(), site, {}, IDENTITY)["items"][0]
    assert res["value"] == pytest.approx(196)
    assert not res["components"][0]["warnings"]


def test_footprint_not_located_is_not_subtracted(site):
    res = execute_plan(paving_minus_pylon(), site, {})["items"][0]
    assert res["value"] == pytest.approx(200)
    assert any("nu a putut fi scăzut" in w for w in res["components"][0]["warnings"])
