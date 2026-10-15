"""Golden snapshot: everything the pipeline computes for a set of drawings, to prove that a change
(a refactor, a dependency upgrade) changes no number.

    uv run python scripts/snapshot.py before.json samples/ more/drawings/
    ... change the code ...
    uv run python scripts/snapshot.py after.json samples/ more/drawings/
    uv run python scripts/compare_snapshots.py before.json after.json

For every drawing it records the units, legends, tables, site region, the digest text, the whole
catalogue, every catalogue entry measured each way that applies to it, and every saved analysis of
the drawing (its plan re-measured). Extraction caches are rebuilt first, so the extraction code is
exercised too; use a scratch data folder (DWG_TAKEOFF_DATA) to keep your own cache untouched.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from dwg_takeoff.analysis.catalogue import expand_entries
from dwg_takeoff.engine.executor import execute_plan
from dwg_takeoff.store import STORE

MEASURES = {
    "surface": ["area"],
    "outline": ["area", "perimeter"],
    "part": ["area"],
    "table": ["area"],
    "linear": ["length", "enclosed_area", "count_groups"],
    "block": ["count"],
    "nested_block": ["count"],
}


def rounded(x):
    if isinstance(x, float):
        return round(x, 6)
    if isinstance(x, dict):
        return {k: rounded(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [rounded(v) for v in x]
    return x


def result_view(res: dict) -> list:
    out = []
    for it in res["items"]:
        comps = [
            {
                "formula": c["formula"],
                "n": c["n_entities"],
                "warnings": c["warnings"],
                "base": rounded(c.get("base_value")),
            }
            for c in it["components"]
        ]
        out.append(
            {
                "id": it["id"],
                "value": rounded(it["value"]),
                "unit": it["unit"],
                "status": it["status"],
                "formula": it["formula"],
                "warnings": it["warnings"],
                "components": comps,
            }
        )
    return out + [{"check": c["message"]} for c in res.get("checks", [])]


def entry_plan(e: dict, site: bool, max_lines: int) -> dict:
    items = []
    for m in MEASURES[e["kind"]]:
        if m in ("enclosed_area", "count_groups") and e["n"] > max_lines:
            continue  # slow on large line groups; the length covers them
        comp = {
            "label": e["id"],
            "measure": m,
            "entries": [e["id"]],
            "subtract_entries": [],
            "sources": [],
            "subtract_sources": [],
            "region": "site" if site else None,
            "factors": [],
            "tolerance_m": 0.05 if m == "enclosed_area" else 0.3,
        }
        items.append({"id": f"{e['id']}/{m}", "label": e["id"], "unit": "", "components": [comp]})
    return {"items": items}


def snapshot(path: Path, max_entries: int, max_lines: int) -> dict:
    p = STORE.add(path)
    for pkl in p.cache_dir.glob("drawing-v*.pkl"):
        pkl.unlink()
    STORE.load(p)
    d, cat = p.drawing, p.digest.get("catalogue") or {"entries": []}
    rec = {
        "units": d.units,
        "scale": d.unit_scale,
        "space": d.space,
        "n_features": len(d.features),
        "legends": [[le.label, le.sample, le.layer, le.pattern, le.block, le.color] for le in d.legends],
        "tables": [[t.tid, sorted(t.objects)] for t in d.tables],
        "text_tables": len(d.text_tables),
        "warnings": d.warnings,
        "site_area": rounded(p.focus["polygon"].area) if p.focus else None,
        "georef": rounded(p.table_transform.to_dict()) if p.table_transform else None,
        "digest_text": p.digest_text,
        "catalogue": rounded(cat),
    }
    entries = {}
    for e in cat["entries"][:max_entries]:
        plan, _ = expand_entries(entry_plan(e, bool(p.focus), max_lines), cat)
        entries[e["id"]] = result_view(execute_plan(plan, d, p.regions, p.table_transform))
    rec["entries"] = entries
    runs = {}
    for f in sorted(p.runs_dir().glob("*/plan.json")):
        plan = json.loads(f.read_text())
        runs[f.parent.name] = result_view(execute_plan(plan, d, p.regions, p.table_transform))
    rec["runs"] = runs
    return rec


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("out", help="snapshot file to write (JSON)")
    ap.add_argument("paths", nargs="+", help="drawings or folders of drawings")
    ap.add_argument("--entries", type=int, default=80, help="catalogue entries measured per drawing (default 80)")
    ap.add_argument("--max-lines", type=int, default=300, help="largest line entry measured as areas / groups")
    args = ap.parse_args()
    files = []
    for p in map(Path, args.paths):
        files += sorted(f for f in p.rglob("*") if f.suffix.lower() in (".dwg", ".dxf")) if p.is_dir() else [p]
    out = {}
    for f in files:
        t = time.time()
        try:
            out[str(f)] = snapshot(f.resolve(), args.entries, args.max_lines)
            status = f"{len(out[str(f)]['entries'])} entries, {len(out[str(f)]['runs'])} runs"
        except Exception as e:  # a drawing that fails is part of the snapshot too
            out[str(f)] = {"error": f"{type(e).__name__}: {e}"}
            status = out[str(f)]["error"][:80]
        print(f"{f.name[:50]:<50} {time.time() - t:6.1f} s  {status}", flush=True)
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, sort_keys=True, indent=0, default=str))


if __name__ == "__main__":
    main()
