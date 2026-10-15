"""Browser tests of the web UI (Chromium, Firefox, WebKit via Playwright) on a synthetic drawing.

Opt-in, they need the Playwright browsers:  uv run playwright install
    DWG_TAKEOFF_UI_TESTS=1 uv run pytest tests/test_ui.py
"""

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("DWG_TAKEOFF_UI_TESTS") != "1", reason="set DWG_TAKEOFF_UI_TESTS=1 (needs `playwright install`)"
)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _get(url):
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.loads(r.read())


def _post(url, payload, ctype="application/json"):
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": ctype}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


@pytest.fixture(scope="module")
def app(tmp_path_factory, drawing):
    data = tmp_path_factory.mktemp("data")
    port = _free_port()
    env = dict(
        os.environ,
        DWG_TAKEOFF_DATA=str(data),
        DWG_TAKEOFF_INPROCESS="1",
        DWG_TAKEOFF_SAMPLES=str(tmp_path_factory.mktemp("no-samples")),
    )
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "dwg_takeoff.web:app", "--port", str(port)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            _get(base + "/api/health")
            break
        except Exception:
            time.sleep(0.2)
    # upload the synthetic drawing (millimetres) and save a run for it
    boundary = "----dwgtakeoff"
    body = (
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="synthetic.dxf"\r\n'
            f"Content-Type: application/octet-stream\r\n\r\n"
        ).encode()
        + Path(drawing.dxf_path).read_bytes()
        + f"\r\n--{boundary}--\r\n".encode()
    )
    pid = _post(base + "/api/projects", body, f"multipart/form-data; boundary={boundary}")["id"]
    for _ in range(150):
        if _get(f"{base}/api/projects/{pid}")["status"] == "ready":
            break
        time.sleep(0.2)

    def src(layer, kinds):
        return {
            "layer": layer,
            "kinds": kinds,
            "pattern": None,
            "color": None,
            "block": None,
            "table_object": None,
            "handles": None,
        }

    def comp(label, measure, sources, factors=()):
        return {
            "label": label,
            "measure": measure,
            "sources": sources,
            "subtract_sources": [],
            "region": None,
            "tolerance_m": 0.25,
            "factors": list(factors),
        }

    def item(iid, unit, c):
        return {
            "id": iid,
            "label": iid,
            "request_text": "",
            "unit": unit,
            "status": "measured",
            "confidence": "high",
            "reasoning": "r",
            "assumptions": [],
            "questions": ["q?"],
            "components": [c],
        }

    cat = _get(f"{base}/api/projects/{pid}/catalogue")
    pav_id = next(e["id"] for e in cat["entries"] if e["kind"] == "surface" and e["layer"] == "PAVAJ_8CM")
    plan = {
        "language": "ro",
        "summary": "test",
        "general_notes": [],
        "questions_for_user": ["Grosime?"],
        "items": [
            item("pavaj", "m²", dict(comp("pavaj", "area", []), entries=[pav_id])),  # chosen by catalogue id
            item("bordura", "m", comp("bordura", "length", [src("BORDURA_20x25", ["line", "closed"])])),
            item(
                "beton",
                "m³",
                comp(
                    "beton",
                    "area",
                    [src("PAVAJ_8CM", ["hatch"])],
                    [{"name": "grosime", "value": 0.15, "unit": "m", "origin": "assumed", "note": ""}],
                ),
            ),
        ],
        "_meta": {"review": {"verdict": "revised", "notes": ["Hașura corectă pentru pavaj."], "changed": ["pavaj"]}},
    }
    _post(f"{base}/api/projects/{pid}/runs", json.dumps({"plan": plan, "query": "test"}).encode())
    yield base, pid
    proc.terminate()
    proc.wait(timeout=10)


@pytest.mark.parametrize("engine", ["chromium", "firefox", "webkit"])
def test_ui(app, engine):
    from playwright.sync_api import sync_playwright

    base, pid = app
    errors = []
    with sync_playwright() as pw:
        browser = getattr(pw, engine).launch()
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.goto(f"{base}/#p={pid}")
        page.wait_for_selector(".qtable tr.item-row", timeout=30000)
        assert page.locator(".qtable tr.item-row").count() == 3
        assert "750" in page.inner_text(".qtable tr.item-row[data-id='pavaj'] .val")  # 750,00 m²
        # the AI's own check of the measured plan: corrected item marked, notes listed
        assert page.locator(".qtable tr.item-row[data-id='pavaj'] .badge.reviewed").count() == 1
        assert page.locator(".qtable .badge.reviewed").count() == 1
        assert "Hașura corectă pentru pavaj." in page.inner_text("#results")
        # zoom with the wheel
        page.wait_for_function("!!document.getElementById('bgImage').getAttribute('href')", timeout=60000)
        w0 = float(page.get_attribute("#svg", "viewBox").split()[2])
        box = page.locator("#viewer").bounding_box()
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        page.mouse.wheel(0, -400)
        page.wait_for_timeout(200)
        assert float(page.get_attribute("#svg", "viewBox").split()[2]) < w0
        # the ruler: two clicks measure a distance (metres, through the drawing units); a known
        # length can calibrate the units
        page.click("#rulerBtn")
        assert "click pe plan" in page.inner_text("#rulerBox")
        cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        page.mouse.click(cx - 100, cy)
        page.mouse.click(cx + 100, cy)
        text = page.inner_text("#rulerBox")
        assert "Segment:" in text and "Segment: 0,00" not in text and "Calibrează" in text
        page.click("#rulerBtn")
        assert page.locator("#rulerBox").is_hidden()
        # factor edit recomputes without the AI
        page.click(".qtable tr.item-row[data-id='beton']")
        inp = page.locator(".detail-box .factor input").first
        inp.fill("0.2")
        inp.dispatch_event("change")
        page.wait_for_function(
            "document.querySelector(\".qtable tr.item-row[data-id='beton'] .val\").textContent.includes('150')"
        )
        # explorer: the catalogue; the page itself never scrolls
        page.click(".tab[data-tab='explore']")
        page.wait_for_selector("#catTable tbody tr.cat-row")
        assert page.evaluate("document.scrollingElement.scrollHeight <= innerHeight + 1")
        row = page.locator("#catTable tr.cat-row").filter(has_text="PAVAJ_8CM").first
        eid = row.get_attribute("data-id")
        assert "750" in row.inner_text()
        # rename it: stored for the drawing, seen by the next AI question
        row.locator("input.cat-label").fill("Pavele parcare (test)")
        row.locator("input.cat-label").press("Enter")
        page.wait_for_function(
            f"""fetch('/api/projects/{pid}/catalogue').then(r => r.json())
            .then(c => c.entries.find(e => e.id === '{eid}').label === 'Pavele parcare (test)')""",
            timeout=10000,
        )
        # add it to the quantities with "+"
        page.locator(f"#catTable tr.cat-row[data-id='{eid}'] button[data-add-entry]").click()
        page.wait_for_function("document.querySelectorAll('.qtable tr.item-row').length === 4", timeout=10000)
        assert "750" in page.inner_text(".qtable tr.item-row >> nth=3")
        page.click(".tab[data-tab='explore']")
        page.wait_for_selector("#catTable tbody tr.cat-row")
        inp = page.locator(f"#catTable tr.cat-row[data-id='{eid}'] input.cat-label")
        inp.fill("")
        inp.press("Enter")
        page.wait_for_function(
            f"""fetch('/api/projects/{pid}/catalogue').then(r => r.json())
            .then(c => c.entries.find(e => e.id === '{eid}').label_source !== 'user')""",
            timeout=10000,
        )
        # the saved analysis measured this entry as "pavaj": one click adopts that as its label
        page.wait_for_selector(f"#catTable tr.cat-row[data-id='{eid}'] [data-adopt]", timeout=10000)
        page.click(f"#catTable tr.cat-row[data-id='{eid}'] [data-adopt]")
        page.wait_for_function(
            f"""fetch('/api/projects/{pid}/catalogue').then(r => r.json())
            .then(c => c.entries.find(e => e.id === '{eid}').label === 'pavaj')""",
            timeout=10000,
        )
        inp = page.locator(f"#catTable tr.cat-row[data-id='{eid}'] input.cat-label")
        inp.fill("")
        inp.press("Enter")
        page.wait_for_function(
            f"""fetch('/api/projects/{pid}/catalogue').then(r => r.json())
            .then(c => c.entries.find(e => e.id === '{eid}').label_source !== 'user')""",
            timeout=10000,
        )
        # units override (mm -> m) multiplies areas by 10^6, and back
        page.select_option("#explorerUnits", "6")
        page.wait_for_function(
            "document.querySelector(\".qtable tr.item-row[data-id='pavaj'] .val\").textContent.includes('750 000 000')",
            timeout=30000,
        )
        page.select_option("#explorerUnits", "")
        page.wait_for_function(
            "!document.querySelector(\".qtable tr.item-row[data-id='pavaj'] .val\").textContent.includes('000 000')",
            timeout=30000,
        )
        browser.close()
    assert not errors, errors
