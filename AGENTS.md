# Agent guide

Instructions for AI coding agents (Codex, Claude Code and others) working in this repository.
Humans: the same information is in [docs/](docs/) and [CONTRIBUTING.md](CONTRIBUTING.md).

## What this is

DWG Takeoff answers quantity-takeoff requests on CAD drawings ("paving area by thickness, curb
length, number of trees") with numbers that can be verified entity by entity. Pipeline:
`cad/` reads DWG/DXF into a `Drawing` → `analysis/` builds the site region, the element catalogue
and the digest → `ai/` turns the request into a JSON plan of catalogue ids → `engine/` measures it
→ the AI reviews what was measured → `web/` (FastAPI + vanilla JS) and `cli.py` present it.
Read [docs/architecture.md](docs/architecture.md) for the module map.

## Commands

```bash
uv sync                                  # install (Python 3.12+)
uv run pytest                            # all tests (~30 s); must pass
uv run ruff check && uv run ruff format --check   # must pass (CI)
npm run lint                             # ESLint for src/dwg_takeoff/web/static (after npm install)
DWG_TAKEOFF_UI_TESTS=1 uv run pytest tests/test_ui.py   # browser tests, when you touch the UI
uv run dwg-takeoff serve                 # the app on http://127.0.0.1:8765
uv run dwg-takeoff catalogue examples/demo-site-plan.dxf   # see what the catalogue holds
uv run dwg-takeoff ask examples/demo-site-plan.dxf "…" --plan plan.json   # measure a plan, no AI
```

Use a scratch data folder for experiments: `DWG_TAKEOFF_DATA=/tmp/x uv run dwg-takeoff …`.
Do not start long-running servers on the default port 8765 if one is already running (the user's).

## Rules

- **The AI never computes a quantity.** Every number comes from `engine/`, with per-entity
  evidence (`Contribution`), a formula and geometry. Do not add code paths where a model's number
  becomes a result.
- **Keep facts and judgement apart.** Anything that can be established without judgement belongs in
  `analysis/` (the catalogue), shown to the AI as evidence; the AI's rules (`ai/prompt.py`) and the
  skill decide how to use it.
- **Language**: code, comments, docs, vocabulary and AI instructions in English; everything the user
  reads (UI, warnings, formulas, progress events) in Romanian, matching the existing wording.
- **Settings** are environment variables read only in `src/dwg_takeoff/config.py`.
- **Cache**: bump `PIPELINE_VERSION` in `store.py` when extraction, the digest or the catalogue
  output changes, or when a pickled class (`cad/model.py`) moves.
- **The skill** `src/dwg_takeoff/ai/skills/dwg-catalogue/SKILL.md` is sent with every planning
  prompt; after editing it run `uv run dwg-takeoff install-skill` (tests compare the copies in
  `.claude/skills/` and `.agents/skills/`). Its planner part ends at `<!-- planner-guide-end -->`.
- **No client data in the repository**: real drawings, their layer names, quantities and requests
  stay in the git-ignored `samples/` folder (see `tests/test_private_samples.py`).
- **Tests**: add a synthetic-drawing test for every behaviour you change (`tests/conftest.py`
  builds DXF drawings with ezdxf). Tests must not write outside temporary folders.
- **Refactors that should not change results**: verify with `scripts/snapshot.py` before and after
  and `scripts/compare_snapshots.py` ([docs/development.md](docs/development.md)).
- **Web UI**: plain ES modules in `web/static/js/`, no build step, no framework; keep the
  module boundaries (`core.js` state and helpers, one module per area).
- Commit only when asked.

## Where things are

| Task | Files |
|---|---|
| reading an entity type | `cad/entities.py` (geometry), `cad/modelspace.py` (blocks, placement) |
| legends, sheets, tables | `cad/legends.py`, `cad/sheets.py`, `cad/tables.py` |
| units inference | `cad/units.py` |
| catalogue entries / relations / prompt line | `analysis/catalogue/build.py` / `relations.py` / `text.py` |
| what the AI reads | `analysis/digest.py`, `ai/prompt.py`, the skill |
| plan schema and checks | `ai/schema.py`, `ai/validation.py` |
| measurements | `engine/measure.py`, `engine/executor.py` |
| HTTP routes | `web/routes/*.py` |
| UI | `web/static/index.html`, `web/static/js/*.js`, `web/static/style.css` |
