# Contributing

Thanks for helping. Bug reports with a drawing that shows the problem are the most useful thing
you can send — if the drawing is confidential, a small DXF that reproduces it is just as good.

## Development setup

```bash
uv sync                      # Python 3.12+, dependencies and dev tools
npm install                  # optional: ESLint for the web UI
uv run playwright install    # optional: browsers for the UI tests
uv run pytest                # ~30 s
```

See [docs/development.md](docs/development.md) for the architecture, conventions, how to add a
measure or an AI backend, and how to test against your own drawings without committing them.

## Pull requests

- One topic per pull request, with a test that fails without the change (most tests build a small
  DXF with ezdxf — see `tests/conftest.py`).
- `uv run pytest`, `uv run ruff check`, `uv run ruff format --check` and, for UI changes,
  `npm run lint` and the browser tests (`DWG_TAKEOFF_UI_TESTS=1 uv run pytest tests/test_ui.py`)
  pass.
- Results must stay verifiable: a new or changed measurement reports per-entity evidence, and the AI
  still only chooses what to measure.
- If a change should not alter any quantity, say how you checked (`scripts/snapshot.py`).
- Update the docs in `docs/` and `CHANGELOG.md` when behaviour changes.
- Never add drawings, layer names or quantities from a client's project.

## Language

Code, comments and documentation are in English. The user interface and the messages users read are
in Romanian; keep the existing wording style when you add some, or ask in the pull request.

## Reporting security issues

Please do not open a public issue — see [SECURITY.md](SECURITY.md).
