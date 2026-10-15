# Development

## Setup

```bash
uv sync                          # Python dependencies, including dev tools (pytest, ruff, playwright)
npm install                      # ESLint for the web UI (optional; the app itself needs no Node)
uv run playwright install        # browsers for the UI tests (optional)
```

The ODA File Converter is only needed for DWG files; the tests use DXF.

## Checks

```bash
uv run pytest                                   # unit, integration, API and CLI tests (~30 s)
DWG_TAKEOFF_UI_TESTS=1 uv run pytest tests/test_ui.py   # browser tests: Chromium, Firefox, WebKit
uv run ruff check && uv run ruff format --check # Python lint and format
npm run lint                                    # web UI lint (ESLint)
```

CI (`.github/workflows/ci.yml`) runs the Python lint, format and tests, and ESLint, on every push
and pull request. Tests never write into the repository: the data folder is redirected to a temporary one.

### Your own drawings as regression tests

Client drawings must not enter the repository, but they make the best tests. Put a drawing in
`samples/` (git-ignored) with a pinned plan and a spec of the values you checked by hand,
`<name>.expected.json` — the format is in
[`tests/test_private_samples.py`](../tests/test_private_samples.py). The test measures the plan on
every run (no AI call) and checks legends, tables, georeferencing, item and component values.

### Golden snapshots for refactors

Before a change that should not alter any result, snapshot a folder of drawings, make the change,
snapshot again and compare:

```bash
export DWG_TAKEOFF_DATA=/tmp/snap-data          # keep your own cache untouched
uv run python scripts/snapshot.py before.json samples/ examples/ ~/drawings/
uv run python scripts/snapshot.py after.json  samples/ examples/ ~/drawings/
uv run python scripts/compare_snapshots.py before.json after.json
```

The snapshot covers the digest text, the catalogue, every entry measured each way and every saved
plan of each drawing.

## Conventions

- **The AI never computes numbers.** New quantities belong in the engine, with evidence; the AI
  only chooses what to measure.
- **Every number is traceable**: a new measure returns contributions per entity (`Contribution`)
  and the geometry to draw.
- **Language**: code, comments, docs, the catalogue vocabulary and the AI instructions in English;
  the user interface and the messages users read (warnings, formulas, progress) in Romanian.
- **Settings** are environment variables, read only in `config.py`.
- **Cache version**: bump `store.PIPELINE_VERSION` when extraction, the digest or the catalogue
  produce something different, or when a pickled class moves.
- **The skill**: `src/dwg_takeoff/ai/skills/dwg-catalogue/SKILL.md` is part of every prompt; after
  editing it run `uv run dwg-takeoff install-skill` (a test checks the installed copies).
- **No client data** in the repository: drawings, layer names, quantities or requests from real
  projects stay in `samples/`.
- Style: ruff (line length 120), ESLint for the UI; modules carry a docstring saying what they are
  for; comments explain *why*.

## Extending

### A new measure

1. Implement it in `engine/measure.py`, returning a `Measurement` (value in drawing units,
   contributions per entity, geometry).
2. Add a function to `engine/executor.py` that selects the entities it applies to, converts to
   metres and fills the evidence and overlay, and register it in `MEASURES`, `MEASURE_DIM` and
   `MEASURE_UNIT`.
3. Add it to the `measure` enum of `ai/schema.py`, explain when to use it in the rules
   (`ai/prompt.py`) or the skill, and show its statistics in the UI (`web/static/js/results.js`).
4. Test it on synthetic geometry (`tests/test_measure.py`) and through a plan.

### A new AI backend

Write a module in `ai/` with `status() -> (bool, str)`, `plan(req: PlanRequest) -> dict` and
`review(req, plan, report) -> dict`, using `prompt.instructions()`, `schema.PLAN_SCHEMA`,
`review.REVIEW_SCHEMA` and `validation.prepare_plan`; report progress with `req.say(...)`, honour
`req.cancel`, raise `PlannerError` with a message a user can act on. Register it in
`ai/__init__.py:BACKENDS` and test it with a fake client (`tests/test_ai_backends.py`).

### Vocabulary

Categories and their terms are in `analysis/vocabulary.py`; National CAD Standard groups in
`NCS_GROUPS`. Adding a category also needs its Romanian name in the UI (`CAT_RO` in
`web/static/js/catalogue.js`).

## Releasing

Update `CHANGELOG.md` and the version in `pyproject.toml`, make sure CI is green, tag `vX.Y.Z`.
