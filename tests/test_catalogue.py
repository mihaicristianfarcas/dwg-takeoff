"""The element catalogue: deterministic entries, their relations, labels and use in plans."""

import ezdxf
import pytest
from ezdxf.math import Vec2
from ezdxf.render.mleader import ConnectionSide
from shapely.geometry import box

from dwg_takeoff.analysis.catalogue import Labels, build_catalogue, catalogue_text, expand_entries, with_labels
from dwg_takeoff.analysis.vocabulary import classify, tokens
from dwg_takeoff.cad import EmbeddedTable, extract, load_doc
from dwg_takeoff.engine.executor import execute_plan


def rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def find(cat, **kw):
    return [e for e in cat["entries"] if all(e.get(k) == v for k, v in kw.items())]


def plan_with(entries, measure="area", unit="m²", subtract=()):
    comp = {
        "label": "c",
        "measure": measure,
        "entries": list(entries),
        "subtract_entries": list(subtract),
        "sources": [],
        "subtract_sources": [],
        "region": None,
        "tolerance_m": 0.3,
        "factors": [],
    }
    return {"items": [{"id": "x", "label": "x", "unit": unit, "components": [comp]}]}


def test_vocabulary():
    assert classify([("layer", "C-ROAD-CURB")])[0].category == "curb"  # NCS: the minor group is the head
    assert classify([("legend", "Concrete curb 20x25")])[0].category == "curb"  # English: last noun
    assert classify([("block", "Tree Clump 1")])[0].category == "tree"
    assert classify([("layer", "TreesOld_2")])[0].category == "tree"
    assert classify([("layer", "drum-borduri 20x25")]) == []  # English only: no guessing
    assert tokens("TreesNew_2 bushes") == ["tree", "new", "2", "bush"]


def test_entries_of_the_synthetic_plan(drawing):
    cat = build_catalogue(drawing)
    pav = find(cat, kind="surface", layer="PAVAJ_8CM")[0]
    assert pav["area"] == pytest.approx(750) and pav["n"] == 1
    copy = find(cat, kind="surface", layer="COPIE_ASCUNSA")[0]
    assert copy["visible"] is False
    assert {"id": copy["id"], "relation": "same surface"}.items() <= next(
        d for d in pav["duplicates"] if d["key"] == copy["key"]
    ).items()
    curb = find(cat, kind="linear", layer="BORDURA_20x25")[0]
    assert curb["length"] == pytest.approx(30 + 28.4 + 80)  # both faces of the island + the doubled edge
    assert curb["length_dedup"] == pytest.approx(30 + 28.4 + 40)  # exact duplicates merged
    stripes = find(cat, kind="linear", layer="MARCAJE")[0]
    assert stripes["width_m"] == pytest.approx(0.12)
    text = catalogue_text(cat, {})
    assert f"{pav['id']} 'PAVAJ_8CM'" in text and "750.00 m²" in text and "HIDDEN" in text


def test_entries_measure_like_their_filters(drawing):
    cat = build_catalogue(drawing)
    pav = find(cat, kind="surface", layer="PAVAJ_8CM")[0]["id"]
    green = find(cat, kind="surface", layer="VERDE")[0]["id"]
    plan, issues = expand_entries(plan_with([pav]), cat)
    assert not issues and plan["items"][0]["components"][0]["sources"][0]["entry"] == pav
    assert execute_plan(plan, drawing, {})["items"][0]["value"] == pytest.approx(750)
    # subtracting an entry; expanding twice changes nothing
    plan, _ = expand_entries(plan_with([pav], subtract=[green]), cat)
    plan, _ = expand_entries(plan, cat)
    assert len(plan["items"][0]["components"][0]["sources"]) == 1
    assert execute_plan(plan, drawing, {})["items"][0]["value"] == pytest.approx(750)  # the island is a hole
    _, issues = expand_entries(plan_with(["S999"]), cat)
    assert issues and "S999" in issues[0]


def test_labels_are_stored_by_key_and_shown(drawing, tmp_path):
    cat = build_catalogue(drawing)
    pav = find(cat, kind="surface", layer="PAVAJ_8CM")[0]
    labels = Labels(tmp_path)
    labels.set(pav["key"], "Pavele 8 cm parcare", "paving")
    e = next(x for x in with_labels(cat, labels.all()) if x["key"] == pav["key"])
    assert e["label"] == "Pavele 8 cm parcare" and e["label_source"] == "user" and e["category"] == "paving"
    assert '"Pavele 8 cm parcare" (user)' in catalogue_text(cat, labels.all())
    labels.set(pav["key"], "", None)  # cleared
    assert pav["key"] not in labels.all()
    with pytest.raises(ValueError):
        labels.set(pav["key"], "x", "no-such-category")


@pytest.fixture(scope="module")
def plan_drawing(tmp_path_factory):
    """Metres. Two rooms numbered 101/102 with a schedule; a sign block named by a multileader; a
    playground placed as one big block (a container); trees whose base point is far away."""
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 6
    msp = doc.modelspace()
    msp.add_lwpolyline(rect(0, 0, 5, 4), close=True, dxfattribs={"layer": "ROOMS"})
    msp.add_lwpolyline(rect(5, 0, 8, 4), close=True, dxfattribs={"layer": "ROOMS"})
    msp.add_text("101", dxfattribs={"layer": "TAGS", "height": 0.25}).set_placement((2, 2))
    msp.add_text("102", dxfattribs={"layer": "TAGS", "height": 0.25}).set_placement((6, 2))
    sign = doc.blocks.new("SIGN")
    sign.add_circle((0, 0), 0.3)
    msp.add_blockref("SIGN", (20, 20), dxfattribs={"layer": "SIGNS"})
    ml = msp.add_multileader_mtext("Standard", dxfattribs={"layer": "NOTES"})
    ml.set_content("Stop sign")
    ml.add_leader_line(ConnectionSide.left, [Vec2(20.1, 20.1)])  # arrow on the sign
    ml.build(insert=Vec2(25, 25))
    play = doc.blocks.new("PLAYGROUND")
    hp = play.add_hatch(color=3)
    hp.paths.add_polyline_path(rect(0, 0, 20, 10), is_closed=True)
    play.add_line((0, 0), (20, 0))
    msp.add_blockref("PLAYGROUND", (30, 0), dxfattribs={"layer": "PLAY"})
    path = tmp_path_factory.mktemp("plan") / "plan.dxf"
    doc.saveas(path)
    d = extract(path, "plan.dxf", load_doc(path))
    d.text_tables = [
        EmbeddedTable("X1", ["Model"], "text", "schedule", [["101", "Living room", 20.0, "102", "Kitchen", 12.5]])
    ]
    return d


def test_rooms_named_through_the_schedule(plan_drawing):
    cat = build_catalogue(plan_drawing)
    rooms = find(cat, kind="outline", layer="ROOMS")[0]
    parts = find(cat, kind="part", parent=rooms["key"])
    assert [(p["id"], p["auto_label"], round(p["area"], 2)) for p in parts] == [
        (f"{rooms['id']}.1", "101 Living room (schedule 20 m²)", 20.0),
        (f"{rooms['id']}.2", "102 Kitchen (schedule 12.5 m²)", 12.0),
    ]
    assert parts[1]["vocab"][0]["category"] == "room"
    plan, issues = expand_entries(plan_with([parts[1]["id"]]), cat)  # one room, by its id
    assert not issues
    assert execute_plan(plan, plan_drawing, {})["items"][0]["value"] == pytest.approx(12)


def test_callout_names_the_symbol_it_points_at(plan_drawing):
    assert [c.text for c in plan_drawing.callouts] == ["Stop sign"]
    cat = build_catalogue(plan_drawing)
    sign = find(cat, kind="block", block="SIGN")[0]
    assert sign["callouts"] == ["Stop sign"] and sign["auto_label"] == "Stop sign"


def test_container_block_content_becomes_entries(plan_drawing):
    cat = build_catalogue(plan_drawing)
    assert cat["containers"] == ["PLAYGROUND"]
    fill = find(cat, kind="surface", in_block="PLAYGROUND")[0]
    assert fill["area"] == pytest.approx(200)
    plan, _ = expand_entries(plan_with([fill["id"]]), cat)
    assert execute_plan(plan, plan_drawing, {})["items"][0]["value"] == pytest.approx(200)
    # only inside the site region
    cat = build_catalogue(plan_drawing, site=box(-1, -1, 10, 10))
    fill = find(cat, kind="surface", in_block="PLAYGROUND")[0]
    assert fill["n_site"] == 0 and "all OUTSIDE site" in catalogue_text(cat, {})


def test_model_space_legend_with_wide_gaps_and_samples_left_out(tmp_path):
    """A legend drawn next to the plan (labels far right of the swatches) names the plan's fills;
    its swatches are samples and are not measured. Equipment lines next to room names are not a
    legend."""
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 6
    msp = doc.modelspace()
    for i, (pat, col, label) in enumerate([("ANSI37", 2, "Pavers"), ("ANSI31", 3, "Asphalt"), ("SOLID", 4, "Lawn")]):
        y = 100 - i * 6
        sw = msp.add_hatch(color=col, dxfattribs={"layer": "PLAN"})
        sw.set_pattern_fill(pat, scale=0.5) if pat != "SOLID" else None
        sw.paths.add_polyline_path(rect(0, y, 13, y + 4), is_closed=True)  # swatch 13 x 4
        msp.add_text(label, dxfattribs={"layer": "LEGEND", "height": 1.3}).set_placement((29, y + 1.5))  # 16 m gap
        h = msp.add_hatch(color=col, dxfattribs={"layer": "PLAN"})  # the real surface, 10 x 10
        h.set_pattern_fill(pat, scale=0.5) if pat != "SOLID" else None
        h.paths.add_polyline_path(rect(100 + 20 * i, 0, 110 + 20 * i, 10), is_closed=True)
    for i, name in enumerate(["HOT KITCHEN", "COLDROOM", "DAIRY"]):  # equipment drawn as lines
        y = 50 - i * 6
        for k in range(4):
            msp.add_line((0, y + k * 0.3), (6, y + k * 0.3), dxfattribs={"layer": "EQUIPMENT"})
        msp.add_text(name, dxfattribs={"layer": "ROOMS", "height": 1.3}).set_placement((8, y))
    path = tmp_path / "legend.dxf"
    doc.saveas(path)
    d = extract(path, "legend.dxf", load_doc(path))
    assert sorted(le.label for le in d.legends) == ["Asphalt", "Lawn", "Pavers"]
    assert len(d.legend_handles) == 3
    cat = build_catalogue(d)
    pavers = next(e for e in cat["entries"] if e["kind"] == "surface" and e["pattern"] == "ANSI37")
    assert pavers["legend"] == ["Pavers"] and pavers["area"] == pytest.approx(100)  # the swatch is left out
    plan, _ = expand_entries(plan_with([pavers["id"]]), cat)
    assert execute_plan(plan, d, {})["items"][0]["value"] == pytest.approx(100)


def test_room_code_missing_from_the_schedule(tmp_path):
    """A room numbered "104" that the schedule lists as "103" (a typo): the only unmatched row
    whose area fits names it; a code nothing fits stays visible as a code."""
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 6
    msp = doc.modelspace()
    for (x0, x1), code in zip([(0, 5), (5, 8), (8, 11), (11, 13)], ["101", "102", "104", "105"], strict=True):
        msp.add_lwpolyline(rect(x0, 0, x1, 4), close=True, dxfattribs={"layer": "ROOMS"})
        msp.add_text(code, dxfattribs={"layer": "TAGS", "height": 0.25}).set_placement(((x0 + x1) / 2, 2))
    msp.add_lwpolyline(rect(-30, -30, 45, 35), dxfattribs={"layer": "FRAME"})  # the sheet around the plan
    path = tmp_path / "rooms.dxf"
    doc.saveas(path)
    d = extract(path, "rooms.dxf", load_doc(path))
    d.text_tables = [
        EmbeddedTable(
            "X1",
            ["Model"],
            "text",
            "schedule",
            [["101", "Living room", 20.0], ["102", "Kitchen", 12.5], ["103", "Bedroom", 12.1]],
        )
    ]
    cat = build_catalogue(d)
    parts = {p["auto_label"]: p for p in find(cat, kind="part")}
    assert set(parts) == {
        "101 Living room (schedule 20 m²)",
        "102 Kitchen (schedule 12.5 m²)",
        "104 Bedroom (schedule row 103, 12.1 m²)",
        "105 (not in the schedule)",
    }
    assert parts["104 Bedroom (schedule row 103, 12.1 m²)"]["vocab"][0]["category"] == "room"
    assert not parts["105 (not in the schedule)"]["vocab"]


def test_fill_edged_by_the_lines_a_legend_names(tmp_path):
    """Buildings drawn as wall lines (legend swatch: an empty outline on the walls' layer) with a
    hatch filling them on another layer: the legend names the lines, the hatch is edged by them."""
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 6
    msp = doc.modelspace()
    for x in (0, 40):
        for off in (0.0, 0.4):  # outer and inner face of the walls
            msp.add_lwpolyline(rect(x - off, -off, x + 20 + off, 10 + off), close=True, dxfattribs={"layer": "WALL"})
        h = msp.add_hatch(color=30, dxfattribs={"layer": "HATCH"})
        h.set_pattern_fill("ANSI31", scale=0.5)
        h.paths.add_polyline_path(rect(x, 0, x + 20, 10), is_closed=True)
        msp.add_line((x - 5, -3), (x + 25, -3), dxfattribs={"layer": "WALL"})  # a detail drawn on the walls' layer
    msp.add_lwpolyline(rect(0, 100, 6, 102), close=True, dxfattribs={"layer": "WALL"})  # the legend swatch
    msp.add_text("Building", dxfattribs={"layer": "LEGEND", "height": 1.0}).set_placement((8, 100.5))
    msp.add_lwpolyline(rect(0, 95, 6, 97), close=True, dxfattribs={"layer": "ROAD"})
    msp.add_text("Road", dxfattribs={"layer": "LEGEND", "height": 1.0}).set_placement((8, 95.5))
    msp.add_lwpolyline(rect(0, 90, 6, 92), close=True, dxfattribs={"layer": "FENCE"})
    msp.add_text("Fence", dxfattribs={"layer": "LEGEND", "height": 1.0}).set_placement((8, 90.5))
    msp.add_line((-10, -20), (80, -20), dxfattribs={"layer": "ROAD"})
    path = tmp_path / "walls.dxf"
    doc.saveas(path)
    d = extract(path, "walls.dxf", load_doc(path))
    assert sorted(le.label for le in d.legends) == ["Building", "Fence", "Road"]
    cat = build_catalogue(d)
    walls = find(cat, kind="linear", layer="WALL")[0]
    fill = find(cat, kind="surface", layer="HATCH")[0]
    assert walls["legend"] == ["Building"] and fill["area"] == pytest.approx(400)
    assert [(x["id"], x["legend"]) for x in fill["edges"]] == [(walls["id"], ["Building"])]
    assert fill["edges"][0]["share"] == 1.0 and walls["edge_of"][0]["id"] == fill["id"]
    line = next(x for x in catalogue_text(cat, {}).splitlines() if x.startswith(fill["id"] + " "))
    assert f"edged by {walls['id']} 'WALL' \"Building\" 100%" in line
