"""Generate `demo-site-plan.dxf`: a small site plan to try DWG Takeoff on (all values known).

    uv run python examples/make_demo.py

Model space, metres: a 70 x 45 m plot with a building (hatched, inside double wall lines), a
parking lot in vehicle pavers with marked bays, sidewalks in smaller pavers, lawns, 20x25 curbs
(some drawn twice, as real drawings often are), trees and lamp posts as blocks, and a legend drawn
next to the plan. Sheet "A1" shows the site at 1:200, which makes the plot the site region.

Expected quantities (what the engine measures; the AI only decides what to measure):
    building footprint        16 x 12 m             = 192 m²
    vehicle pavers (8 cm)     parking 40 x 20 m     = 800 m²
    sidewalk pavers (6 cm)    3 m strips            = 228 m²   (2 strips: 40 x 3 + 36 x 3)
    lawn                      two beds              = 255 m²
    curbs 20x25               edge of the parking   = 120 m    (two edges drawn twice: 200 m drawn)
    trees                     10 blocks
    lamp posts                4 blocks
    parking bay lines         16 x 5 m, 0.12 m wide = 80 m, 9.6 m² painted
"""

from __future__ import annotations

from pathlib import Path

import ezdxf
from ezdxf.enums import TextEntityAlignment

OUT = Path(__file__).with_name("demo-site-plan.dxf")


def rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def hatch(msp, layer, pattern, color, pts, scale=0.5):
    h = msp.add_hatch(color=color, dxfattribs={"layer": layer})
    if pattern != "SOLID":
        h.set_pattern_fill(pattern, scale=scale)
    h.paths.add_polyline_path(pts, is_closed=True)
    return h


def main() -> None:
    doc = ezdxf.new("R2018", setup=True)
    doc.header["$INSUNITS"] = 6  # metres
    for name, color in (
        ("PLOT", 8),
        ("BUILDING-WALLS", 7),
        ("BUILDING-HATCH", 30),
        ("PAVERS-8CM", 9),
        ("PAVERS-6CM", 252),
        ("LAWN", 3),
        ("CURB-20x25", 1),
        ("MARKINGS", 7),
        ("PLANTING", 3),
        ("LIGHTING", 2),
        ("TEXT", 7),
        ("LEGEND", 7),
    ):
        doc.layers.add(name, color=color)
    msp = doc.modelspace()

    # plot boundary
    msp.add_lwpolyline(rect(0, 0, 70, 45), close=True, dxfattribs={"layer": "PLOT"})

    # building: hatch inside double wall lines (outer face 0.3 m outside the hatch)
    hatch(msp, "BUILDING-HATCH", "ANSI31", 30, rect(48, 25, 64, 37), scale=0.4)
    msp.add_lwpolyline(rect(48, 25, 64, 37), close=True, dxfattribs={"layer": "BUILDING-WALLS"})
    msp.add_lwpolyline(rect(47.7, 24.7, 64.3, 37.3), close=True, dxfattribs={"layer": "BUILDING-WALLS"})

    # parking in vehicle pavers, with curbs along its edges (two edges drawn twice)
    hatch(msp, "PAVERS-8CM", "AR-HBONE", 9, rect(4, 4, 44, 24), scale=0.03)
    msp.add_lwpolyline(rect(4, 4, 44, 24), close=True, dxfattribs={"layer": "CURB-20x25"})
    msp.add_line((4, 4), (44, 4), dxfattribs={"layer": "CURB-20x25"})
    msp.add_line((4, 24), (44, 24), dxfattribs={"layer": "CURB-20x25"})
    # parking bays: 16 stripes 5 m long, 0.12 m wide, along the top edge
    for i in range(16):
        x = 6 + i * 2.5
        msp.add_lwpolyline([(x, 24), (x, 19)], dxfattribs={"layer": "MARKINGS", "const_width": 0.12})

    # sidewalks in smaller pavers
    hatch(msp, "PAVERS-6CM", "AR-B816", 252, rect(4, 24, 44, 27), scale=0.02)
    hatch(msp, "PAVERS-6CM", "AR-B816", 252, rect(44, 4, 47, 40), scale=0.02)

    # lawns
    hatch(msp, "LAWN", "SOLID", 3, rect(4, 27, 19, 40))  # 15 x 13 = 195
    hatch(msp, "LAWN", "SOLID", 3, rect(48, 4, 64, 7.75))  # 16 x 3.75 = 60

    # trees and lamp posts
    tree = doc.blocks.new("TREE-DECIDUOUS")
    tree.add_circle((0, 0), 2.5)
    tree.add_circle((0, 0), 0.25)
    for x, y in ((7, 31), (11, 36), (15, 31), (24, 33), (30, 37), (36, 33), (41, 37), (52, 6), (58, 6), (62, 6)):
        msp.add_blockref("TREE-DECIDUOUS", (x, y), dxfattribs={"layer": "PLANTING"})
    lamp = doc.blocks.new("LAMP-POST")
    lamp.add_circle((0, 0), 0.3)
    lamp.add_line((-0.3, 0), (0.3, 0))
    lamp.add_line((0, -0.3), (0, 0.3))
    for x, y in ((4, 14), (44, 14), (24, 2.5), (46, 30)):
        msp.add_blockref("LAMP-POST", (x, y), dxfattribs={"layer": "LIGHTING"})

    # labels on the plan
    for text, x, y in (("PARKING", 22, 12), ("BUILDING", 54, 31), ("LAWN", 9, 38)):
        msp.add_text(text, height=1.0, dxfattribs={"layer": "TEXT"}).set_placement(
            (x, y), align=TextEntityAlignment.MIDDLE_CENTER
        )

    # legend next to the plan: a column of swatches with their labels
    legend = (
        ("PAVERS-8CM", "AR-HBONE", 9, "Vehicle pavers 8 cm"),
        ("PAVERS-6CM", "AR-B816", 252, "Sidewalk pavers 6 cm"),
        ("LAWN", "SOLID", 3, "Lawn"),
        ("BUILDING-HATCH", "ANSI31", 30, "Building"),
    )
    for i, (layer, pattern, color, label) in enumerate(legend):
        y = 40 - i * 4
        hatch(
            msp,
            layer,
            pattern,
            color,
            rect(80, y, 86, y + 2.5),
            scale={"AR-HBONE": 0.03, "AR-B816": 0.02}.get(pattern, 0.4),
        )
        msp.add_lwpolyline(rect(80, y, 86, y + 2.5), close=True, dxfattribs={"layer": "LEGEND"})
        msp.add_text(label, height=0.8, dxfattribs={"layer": "LEGEND"}).set_placement((88, y + 1))
    msp.add_text("LEGEND", height=1.2, dxfattribs={"layer": "LEGEND"}).set_placement((80, 44))

    # sheet A1 with a 1:200 viewport on the plot: the site region
    sheet = doc.layouts.new("A1")
    sheet.page_setup(size=(841, 594), margins=(10, 10, 10, 10), units="mm")
    sheet.add_viewport(center=(400, 300), size=(370, 240), view_center_point=(35, 22.5), view_height=48)
    sheet.add_text("SITE PLAN 1:200", height=8, dxfattribs={"layer": "TEXT"}).set_placement((215, 440))

    doc.saveas(OUT)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
