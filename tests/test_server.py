"""HTTP API: input validation and same-origin protection (no AI, temporary data folder)."""

import ezdxf
import pytest
from fastapi.testclient import TestClient

from dwg_takeoff import config, web
from dwg_takeoff.store import STORE


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / "cache")
    doc = ezdxf.new("R2018")
    doc.modelspace().add_lwpolyline([(0, 0), (10, 0), (10, 5), (0, 5)], close=True, dxfattribs={"layer": "A"})
    path = tmp_path / "x.dxf"
    doc.saveas(path)
    p = STORE.add(path)
    STORE.load(p)
    yield TestClient(web.app), p  # no context manager: the startup scan of samples/ is skipped
    STORE.projects.pop(p.id, None)


def test_cross_origin_writes_refused(client):
    c, p = client
    r = c.put(f"/api/projects/{p.id}/info", json={"notes": "x"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    r = c.put(f"/api/projects/{p.id}/info", json={"notes": "placa 18 cm"}, headers={"Origin": "http://testserver"})
    assert r.status_code == 200 and r.json()["notes"] == "placa 18 cm"
    assert c.get(f"/api/projects/{p.id}/info", headers={"Origin": "https://evil.example"}).status_code == 200


def test_reference_ids_and_run_names_validated(client):
    c, p = client
    r = c.post(f"/api/projects/{p.id}/references", files={"file": ("caiet.txt", b"beton 20 cm")})
    assert r.status_code == 200 and len(r.json()["documents"]) == 1
    assert c.delete(f"/api/projects/{p.id}/references/*").status_code == 404
    assert len(c.get(f"/api/projects/{p.id}/info").json()["documents"]) == 1  # nothing was wiped
    assert c.post(f"/api/projects/{p.id}/references", files={"file": ("x.exe", b"MZ")}).status_code == 400
    for bad in ("%2E%2E", "_deleted_x", "20261015"):
        assert c.get(f"/api/projects/{p.id}/runs/{bad}").status_code == 404
        assert c.delete(f"/api/projects/{p.id}/runs/{bad}").status_code == 404


def test_units_override_roundtrip(client):
    c, p = client
    assert c.post(f"/api/projects/{p.id}/units", json={"code": 4}).json()["unit_info"]["code"] == 4
    assert c.post(f"/api/projects/{p.id}/units", json={"scale": 0.1}).json()["unit_scale"] == pytest.approx(0.1)
    assert c.post(f"/api/projects/{p.id}/units", json={"scale": -1}).status_code == 400
    assert c.post(f"/api/projects/{p.id}/units", json={}).json()["unit_info"]["source"] != "override"
