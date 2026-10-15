## What and why

## How it was checked
- [ ] `uv run pytest`, `uv run ruff check`, `uv run ruff format --check`
- [ ] a test that fails without this change
- [ ] UI changes: `npm run lint` and `DWG_TAKEOFF_UI_TESTS=1 uv run pytest tests/test_ui.py`
- [ ] no quantity changed unintentionally (`scripts/snapshot.py`), or the changes are explained
- [ ] docs / `CHANGELOG.md` updated; no client drawings or data added
