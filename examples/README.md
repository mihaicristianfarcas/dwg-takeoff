# examples/

`demo-site-plan.dxf` — a small site plan in metres to try DWG Takeoff on: a legend drawn next to
the plan, a building hatched inside double wall lines, a parking lot with marked bays, sidewalks,
lawns, curbs (two edges drawn twice), trees and lamp posts as blocks, and a sheet with a 1:200
viewport that defines the site region. The expected quantities are listed in
[`make_demo.py`](make_demo.py), which generates the file:

```bash
uv run python examples/make_demo.py
DWG_TAKEOFF_SAMPLES=examples uv run dwg-takeoff serve
uv run dwg-takeoff catalogue examples/demo-site-plan.dxf
```
