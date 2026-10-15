"""End-to-end pipeline test (DXF -> extraction -> digest -> plan execution) on a small drawing
whose quantities are known by construction. Units are millimetres to exercise unit scaling."""

import pytest

from dwg_takeoff.analysis.digest import build_digest, digest_to_text
from dwg_takeoff.engine.executor import execute_plan


def src(layer, kinds, pattern=None):
    return {"layer": layer, "kinds": kinds, "pattern": pattern, "block": None, "table_object": None, "handles": None}


def item(iid, measure, sources, unit, factors=(), tol=None):
    return {
        "id": iid,
        "label": iid,
        "request_text": "",
        "unit": unit,
        "status": "measured",
        "confidence": "high",
        "reasoning": "",
        "assumptions": [],
        "questions": [],
        "components": [
            {
                "label": iid,
                "measure": measure,
                "sources": sources,
                "subtract_sources": [],
                "region": None,
                "tolerance_m": tol,
                "factors": list(factors),
            }
        ],
    }


def test_units_and_digest(drawing):
    assert drawing.unit_scale == 0.001
    dg = build_digest(drawing)
    text = digest_to_text(dg)
    assert "PAVAJ_8CM" in text and "HIDDEN" in text  # the frozen copy is flagged
    assert text.rstrip().splitlines()[-1].startswith(("S", "O", "L", "B", "N", "T"))  # ends with the catalogue


def test_quantities(drawing):
    plan = {
        "items": [
            item("pavaj8", "area", [src("PAVAJ_8CM", ["hatch"]), src("COPIE_ASCUNSA", ["hatch"])], "m²"),
            item("pavaj6", "area", [src("TROTUAR_6CM", ["hatch"])], "m²"),
            item("verde", "area", [src("VERDE", ["hatch"])], "m²"),
            item("bordura", "length", [src("BORDURA_20x25", ["line", "closed"])], "m", tol=0.25),
            item("cladire", "area", [src("CLADIRE", ["closed"])], "m²"),
            item(
                "beton",
                "area",
                [src("PAVAJ_8CM", ["hatch"])],
                "m³",
                factors=[{"name": "grosime", "value": 0.15, "unit": "m", "origin": "assumed", "note": ""}],
            ),
            item("vopsea", "strip_area", [src("MARCAJE", ["line"])], "m²"),
        ]
    }
    res = execute_plan(plan, drawing, {})
    v = {i["id"]: i for i in res["items"]}
    assert v["pavaj8"]["value"] == pytest.approx(750)  # 800 - 50 island; frozen copy not double counted
    assert v["pavaj8"]["components"][0]["stats"]["raw_sum"] == pytest.approx(1500)
    assert v["pavaj6"]["value"] == pytest.approx(80)
    assert v["verde"]["value"] == pytest.approx(50)
    assert v["bordura"]["value"] == pytest.approx(70, rel=1e-3)  # 30 m island + 40 m edge
    assert v["cladire"]["value"] == pytest.approx(96)
    assert v["beton"]["value"] == pytest.approx(112.5) and v["beton"]["unit"] == "m³"
    assert v["beton"]["status"] == "assumption_based"
    assert v["vopsea"]["value"] == pytest.approx(3 * 5 * 0.12, rel=1e-3)
    assert any("înghețat" in w for w in v["pavaj8"]["components"][0]["warnings"])
