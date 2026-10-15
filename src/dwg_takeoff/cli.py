"""Command line interface (see docs/cli.md).

dwg-takeoff serve [--port 8765]                  start the web app
dwg-takeoff inspect FILE.dwg [FILE ...]          quick health check: units, legends, tables, timings
dwg-takeoff digest FILE.dwg                      print what the AI sees about the drawing
dwg-takeoff catalogue FILE.dwg [--all|--search q|--entry S8|--csv f]   the element catalogue
dwg-takeoff ask FILE.dwg "query" [--plan p.json] run the AI planner + engine, print the results
dwg-takeoff install-skill [--dir .]              install the dwg-catalogue skill for Claude Code / Codex
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from . import __version__
from .ai.planner import make_plan
from .ai.prompt import SKILL_FILE
from .ai.tools import DrawingTools
from .analysis.catalogue import catalogue_text, expand_entries, with_labels, write_csv
from .engine.executor import execute_plan
from .formatting import num_ro
from .project_info import ProjectInfo
from .store import STORE


def _load(path: str):
    p = STORE.add(path)
    STORE.load(p)
    return p


def print_result(res: dict) -> None:
    for it in res["items"]:
        v = "—" if it["value"] is None else f"{num_ro(it['value'], 0 if it['unit'] == 'buc' else 2)} {it['unit']}"
        print(f"\n■ {it['label']}: {v}   [{it['status']}, confidence {it['confidence']}]")
        print(f"  {it['formula']}")
        for c in it["components"]:
            print(f"   • {c['label']}: {c['formula']}  ({c['n_entities']} entities)")
            st = c.get("stats") or {}
            if "raw_sum" in st:
                print(f"     raw drawn sum {num_ro(st['raw_sum'])} -> counted {num_ro(c['base_value'])}")
            for w in c["warnings"]:
                print(f"     ! {w}")
        for a in it["assumptions"]:
            print(f"   assumption: {a}")
        print(f"   reasoning: {it['reasoning']}")
    for ch in res.get("checks", []):
        print(f"\n⚠ {ch['message']}")
    rv = ((res.get("plan") or {}).get("_meta") or {}).get("review")
    if rv:
        if rv.get("error"):
            print(f"\nreview: failed ({rv['error'][:200]})")
        else:
            changed = ", ".join(rv.get("changed") or []) or "nothing changed"
            print(
                f"\nreview ({rv.get('seconds')} s): {rv.get('verdict')}; {changed}"
                + (" [corrections rejected]" if rv.get("rejected") else "")
            )
            for n in rv.get("notes") or []:
                print(f"   - {n}")


def show_catalogue(p, args) -> None:
    cat = p.digest.get("catalogue") or {"entries": []}
    labels = p.labels()
    if args.csv:
        write_csv(cat, labels, Path(args.csv))
        print(f"{len(cat['entries'])} entries -> {args.csv}")
    elif args.entry:
        e = next((x for x in with_labels(cat, labels) if x["id"] == args.entry.upper()), None)
        if e is None:
            sys.exit(f"no entry {args.entry}")
        print(json.dumps(e, ensure_ascii=False, indent=1))
    elif args.search:
        res = DrawingTools(p.drawing, catalogue=cat, labels=labels).catalogue_search(args.search, 200)
        print(f"{res['total']} entries match")
        print("\n".join(res["entries"]))
    else:
        print(catalogue_text(cat, labels, max_entries=10**6 if args.all else 300))


def install_skill(root: Path) -> list[Path]:
    """Copy the dwg-catalogue skill to where Claude Code (.claude/skills) and Codex (.agents/skills)
    look for project skills."""
    out = []
    for base in (".claude", ".agents"):
        dest = root / base / "skills" / SKILL_FILE.parent.name
        dest.mkdir(parents=True, exist_ok=True)
        for f in SKILL_FILE.parent.iterdir():
            if f.is_file():
                shutil.copyfile(f, dest / f.name)
        out.append(dest / SKILL_FILE.name)
    return out


def inspect(path: str) -> None:
    """One drawing: what was found and what to double-check before asking for quantities."""
    try:
        p = _load(path)
    except Exception as e:
        print(f"\n✗ {Path(path).name}: {type(e).__name__}: {e}")
        return
    d, ui = p.drawing, p.drawing.unit_info or {}
    kinds = {}
    for f in d.features:
        kinds[f.kind] = kinds.get(f.kind, 0) + 1
    print(f"\n■ {p.name}  ({p.info().get('dwg_version') or d.dxf_version})")
    print(f"  units: {d.units}  [{ui.get('confidence', '?')} confidence]")
    for ev in ui.get("evidence", [])[:3]:
        print(f"    · {ev}")
    n = f"{len(d.features):,}".replace(",", " ")
    print(f"  measured space: {d.space}; {n} entities: " + ", ".join(f"{k} {v}" for k, v in sorted(kinds.items())))
    print(
        f"  layers {len(d.layers)}, legend entries {len(d.legends)}, tables {len(d.tables)}, text tables {len(d.text_tables)}"
    )
    if p.focus:
        area = f"{p.focus['polygon'].area * d.unit_scale**2:,.0f}".replace(",", " ")
        print(f"  site region: sheets {', '.join(p.focus['sheets'])}; {area} m²")
    else:
        print("  site region: none (whole drawing is used)")
    if p.table_transform is not None:
        print(
            f"  setting-out tables georeferenced: {p.table_transform.matched} points, RMS {p.table_transform.rms * 1000:.1f} mm"
        )
    for w in d.warnings + ([f"unbound xrefs: {', '.join(d.xrefs)}"] if d.xrefs else []):
        print(f"  ! {w}")
    print(f"  timings: {p.timings}")


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="dwg-takeoff",
        description="Quantity takeoff from DWG/DXF drawings with verifiable evidence.",
        epilog="Documentation: https://github.com/mihaicristianfarcas/dwg-takeoff/tree/main/docs",
    )
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True, metavar="COMMAND")
    s = sub.add_parser("serve", help="start the web app")
    s.add_argument("--host", default="127.0.0.1", help="interface to listen on (default: 127.0.0.1, this machine only)")
    s.add_argument("--port", type=int, default=8765, help="port (default: 8765)")
    i = sub.add_parser("inspect", help="health check of drawings: units, legends, tables, site region, timings")
    i.add_argument("files", nargs="+", metavar="FILE")
    d = sub.add_parser("digest", help="print what the AI reads about a drawing")
    d.add_argument("file", metavar="FILE")
    c = sub.add_parser("catalogue", help="show the element catalogue of a drawing")
    c.add_argument("file", metavar="FILE")
    c.add_argument("--all", action="store_true", help="every entry (default: the 300 most relevant)")
    c.add_argument("--search", help="entries whose id, label, layer, block, legend, callout or text match")
    c.add_argument("--entry", help="one entry with its filters and evidence (JSON)")
    c.add_argument("--csv", help="write the whole catalogue as CSV here")
    a = sub.add_parser("ask", help="answer a takeoff request: AI plan + measurement, printed with the evidence")
    a.add_argument("file", metavar="FILE")
    a.add_argument("query", metavar="REQUEST", help="what to measure, in plain words (any language)")
    a.add_argument("--plan", help="measure this plan JSON instead of calling the AI (catalogue ids allowed)")
    a.add_argument(
        "--backend", choices=["codex", "anthropic", "openai"], help="AI backend (default: DWG_TAKEOFF_AI or codex)"
    )
    a.add_argument("--model", help="model name for the backend (default: the backend's configured model)")
    a.add_argument("--effort", choices=["low", "medium", "high"], help="reasoning effort (default: medium)")
    a.add_argument("--info", help="project information for this run (thicknesses, client answers)")
    a.add_argument("--no-review", action="store_true", help="skip the AI check of the measured results")
    a.add_argument("--json", help="write the full result JSON here")
    k = sub.add_parser("install-skill", help="install the dwg-catalogue skill for Claude Code and Codex")
    k.add_argument("--dir", default=".", help="repository root (default: current directory)")
    args = ap.parse_args(argv)

    if args.cmd == "serve":
        import uvicorn

        uvicorn.run("dwg_takeoff.web:app", host=args.host, port=args.port, log_level="info")
        return
    if args.cmd == "inspect":
        for f in args.files:
            inspect(f)
        return
    if args.cmd == "install-skill":
        for path in install_skill(Path(args.dir)):
            print(f"installed {path}")
        return
    if args.cmd == "catalogue":
        show_catalogue(_load(args.file), args)
        return
    p = _load(args.file)
    if args.cmd == "digest":
        print(p.digest_text)
        return
    if args.cmd == "ask":
        if args.plan:
            plan = json.loads(Path(args.plan).read_text())
            _, issues = expand_entries(plan, p.digest["catalogue"])  # a plan may name catalogue entries
            for issue in issues:
                print(f"  ! {issue}", file=sys.stderr)
        else:
            run_dir = p.new_run_dir()

            def show(e):
                if e.kind in ("stage", "done", "thought", "lookup", "warning", "usage"):
                    print(
                        f"  [{e.kind}] {e.text}" + (f"  ({e.detail})" if e.detail and e.kind != "thought" else ""),
                        file=sys.stderr,
                    )

            info = ProjectInfo(p.cache_dir).prompt_text()
            if args.info:
                info = (info + "\n\n" if info else "") + "Notes from the user / client answers:\n" + args.info
            if info:
                print(f"  [info] project information included ({len(info)} characters)", file=sys.stderr)
            plan = make_plan(
                args.query,
                p.drawing,
                p.digest,
                p.digest_text,
                p.focus["polygon"] if p.focus else None,
                run_dir,
                model=args.model,
                effort=args.effort,
                on_event=show,
                backend=args.backend,
                table_transform=p.table_transform,
                project_info=info,
                regions=p.regions,
                review=not args.no_review,
                labels=p.labels(),
            )
            print(f"plan: {run_dir / 'plan.json'} ({plan['_meta']['seconds']} s)", file=sys.stderr)
        res = execute_plan(plan, p.drawing, p.regions, p.table_transform)
        res["plan"] = plan
        res["query"] = args.query
        if not args.plan:
            res["run"] = run_dir.name
            (run_dir / "result.json").write_text(json.dumps(res, ensure_ascii=False, default=str))
        print_result(res)
        if args.json:
            Path(args.json).write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
