"""Shared fixtures: a small synthetic drawing (millimetres) with known quantities."""

import ezdxf
import pytest

from dwg_takeoff.cad import extract, load_doc


def rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


@pytest.fixture(scope="session", autouse=True)
def data_dir(tmp_path_factory):
    """Tests never write into the repository's data folder."""
    from dwg_takeoff import config

    d = tmp_path_factory.mktemp("data")
    config.DATA_DIR, config.CACHE_DIR, config.UPLOADS_DIR = d, d / "cache", d / "uploads"
    return d


@pytest.fixture(scope="session")
def drawing(tmp_path_factory):
    doc = ezdxf.new("R2018", setup=True)
    doc.header["$INSUNITS"] = 4  # mm
    msp = doc.modelspace()
    for name in ("PAVAJ_8CM", "TROTUAR_6CM", "VERDE", "BORDURA_20x25", "CLADIRE", "MARCAJE"):
        doc.layers.add(name)
    doc.layers.add("COPIE_ASCUNSA").freeze()
    # 40 x 20 m parking with a 10 x 5 m island (hole)
    h = msp.add_hatch(dxfattribs={"layer": "PAVAJ_8CM"})
    h.paths.add_polyline_path(rect(0, 0, 40000, 20000), is_closed=True, flags=1)
    h.paths.add_polyline_path(rect(15000, 7500, 25000, 12500), is_closed=True, flags=16)
    # the same parking traced again on a frozen layer (duplicate representation)
    h2 = msp.add_hatch(dxfattribs={"layer": "COPIE_ASCUNSA"})
    h2.paths.add_polyline_path(rect(0, 0, 40000, 20000), is_closed=True, flags=1)
    h2.paths.add_polyline_path(rect(15000, 7500, 25000, 12500), is_closed=True, flags=16)
    # 40 x 2 m sidewalk, pattern hatch
    h3 = msp.add_hatch(dxfattribs={"layer": "TROTUAR_6CM"})
    h3.set_pattern_fill("ANSI37", scale=100)
    h3.paths.add_polyline_path(rect(0, 20000, 40000, 22000), is_closed=True)
    # island green
    h4 = msp.add_hatch(dxfattribs={"layer": "VERDE"})
    h4.paths.add_polyline_path(rect(15000, 7500, 25000, 12500), is_closed=True)
    # curbs: island drawn with both faces (200 mm apart), sidewalk edge drawn twice
    msp.add_lwpolyline(rect(15000, 7500, 25000, 12500), close=True, dxfattribs={"layer": "BORDURA_20x25"})
    msp.add_lwpolyline(rect(15200, 7700, 24800, 12300), close=True, dxfattribs={"layer": "BORDURA_20x25"})
    msp.add_line((0, 20000), (40000, 20000), dxfattribs={"layer": "BORDURA_20x25"})
    msp.add_line((0, 20000), (40000, 20000), dxfattribs={"layer": "BORDURA_20x25"})
    # building 12 x 8 m and three 5 m parking stripes 120 mm wide
    msp.add_lwpolyline(rect(42000, 0, 54000, 8000), close=True, dxfattribs={"layer": "CLADIRE"})
    for x in (2500, 5000, 7500):
        msp.add_lwpolyline([(x, 0), (x, 5000)], dxfattribs={"layer": "MARCAJE", "const_width": 120})
    doc.layers.add("TEXT")
    msp.add_text("PARCARE PAVELE BETON 8 cm", dxfattribs={"layer": "TEXT", "height": 500}).set_placement((2000, 2000))
    msp.add_text("Terasă exterioară", dxfattribs={"layer": "TEXT", "height": 400}).set_placement((2000, 20500))
    path = tmp_path_factory.mktemp("dxf") / "synthetic.dxf"
    doc.saveas(path)
    return extract(path, "synthetic.dxf", load_doc(path))
