# samples/

Put your own `.dwg` / `.dxf` drawings here. Everything in this folder except this file is
git-ignored, so client drawings never end up in the repository.

- The web server loads every drawing in this folder at startup (the first one is selected).
- **Private regression tests**: next to a drawing, add a pinned plan (`<name>.plan.json`, e.g. the
  `plan.json` of an analysis you checked by hand) and `<name>.expected.json` with the values you
  verified. `uv run pytest` then measures it on every run; the spec format is described in
  [`tests/test_private_samples.py`](../tests/test_private_samples.py). Converted drawings are
  cached in `samples/.cache/`.
