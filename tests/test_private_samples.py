"""Regression tests on your own drawings, kept out of the repository.

Put a drawing in `samples/` (git-ignored) with a spec next to it, `<anything>.expected.json`:

    {
      "drawing": "site-plan.dwg",            # relative to the spec
      "plan": "site-plan.plan.json",         # a pinned takeoff plan (entry ids or filters)
      "legend_labels": ["Paving 8 cm"],      # optional: legend entries that must be found
      "table_objects": ["Pylon"],            # optional: setting-out table objects
      "georeferenced": {"min_matched": 8, "max_rms_m": 0.01},   # optional
      "items": {"paving_8": 1610.46},        # expected item values
      "components": {"curbs": [595.77, 122.63]},  # optional: expected component base values
      "checks": ["line_overlap"],            # optional: cross-check types that must be reported
      "tolerance": 0.05                      # absolute tolerance of every value (default 0.05)
    }

A pinned plan is any `plan.json` of an analysis you checked by hand (data/cache/<id>/runs/<run>/),
so no AI call is needed. Without specs the test is skipped; DWG specs are skipped when the ODA File
Converter is not installed. Converted drawings are cached in `samples/.cache/`.
"""

import json
from pathlib import Path

import pytest

from dwg_takeoff.cad.convert import converter_available

SAMPLES = Path(__file__).resolve().parents[1] / "samples"
SPECS = sorted(SAMPLES.rglob("*.expected.json")) if SAMPLES.is_dir() else []


def _id(spec: Path) -> str:
    return spec.name.removesuffix(".expected.json")


@pytest.fixture(scope="module", params=SPECS or [None], ids=[_id(s) for s in SPECS] or ["none"])
def case(request):
    spec_path = request.param
    if spec_path is None:
        pytest.skip("no samples/*.expected.json (see the module docstring)")
    spec = json.loads(spec_path.read_text())
    drawing = spec_path.parent / spec["drawing"]
    if not drawing.exists():
        pytest.skip(f"{drawing.name} missing")
    if drawing.suffix.lower() == ".dwg" and not converter_available():
        pytest.skip("ODA File Converter not installed")
    from dwg_takeoff import config
    from dwg_takeoff.analysis.catalogue import expand_entries
    from dwg_takeoff.engine.executor import execute_plan
    from dwg_takeoff.store import STORE

    cache = config.CACHE_DIR
    config.CACHE_DIR = SAMPLES / ".cache"  # kept between runs, next to the private drawings
    try:
        project = STORE.add(drawing)
        STORE.load(project)
    finally:
        config.CACHE_DIR = cache
    result = None
    if spec.get("plan"):
        plan = json.loads((spec_path.parent / spec["plan"]).read_text())
        expand_entries(plan, project.digest["catalogue"])
        result = execute_plan(plan, project.drawing, project.regions, project.table_transform)
    return spec, project, result


def test_legends_and_tables(case):
    spec, project, _ = case
    labels = {le.label for le in project.drawing.legends}
    assert set(spec.get("legend_labels", [])) <= labels
    objects = {o for t in project.drawing.tables for o in t.objects}
    assert set(spec.get("table_objects", [])) <= objects
    geo = spec.get("georeferenced")
    if geo:
        tr = project.table_transform
        assert tr is not None and tr.matched >= geo.get("min_matched", 4)
        assert tr.rms <= geo.get("max_rms_m", 0.01)


def test_quantities(case):
    spec, _, result = case
    if result is None:
        pytest.skip("no pinned plan")
    tol = spec.get("tolerance", 0.05)
    items = {it["id"]: it for it in result["items"]}
    for iid, value in spec.get("items", {}).items():
        assert items[iid]["value"] == pytest.approx(value, abs=tol), iid
    for iid, values in spec.get("components", {}).items():
        got = [c["base_value"] for c in items[iid]["components"]]
        assert got == pytest.approx(values, abs=tol), iid
    reported = {ch["type"] for ch in result["checks"]}
    assert set(spec.get("checks", [])) <= reported
