# Getting started

## 1. Install

You need Python 3.12 or newer and [uv](https://docs.astral.sh/uv/getting-started/installation/).

```bash
git clone https://github.com/mihaicristianfarcas/dwg-takeoff.git
cd dwg-takeoff
uv sync
```

### DWG files: the ODA File Converter

DXF files are read directly. DWG files are converted to DXF first with the free
[ODA File Converter](https://www.opendesign.com/guestfiles/oda_file_converter) (Open Design
Alliance; free to use, closed source):

| OS | Install | Found at |
|---|---|---|
| macOS | open the `.dmg`, copy `ODAFileConverter.app` to `/Applications` (or `~/Applications`) | automatically |
| Linux | install the `.deb` / `.rpm` (or AppImage) | `ODAFileConverter` on the `PATH` or `/usr/bin`; runs headless (`QT_QPA_PLATFORM=offscreen` is set for you) |
| Windows | run the installer | `C:\Program Files\ODA\ODAFileConverter*\` |

Anywhere else: set `DWG_TAKEOFF_ODA` to the executable. The status chip *ODA* in the app turns
green when the converter is found. Converted files are cached, so each drawing is converted once.

### An AI backend

The AI only plans what to measure. Pick one (they are interchangeable; the app shows which ones are
ready, and you can switch per question):

| Backend | Cost | Setup |
|---|---|---|
| `codex` (default) | your ChatGPT plan (Plus / Pro / Team…) | `npm i -g @openai/codex`, then `codex login` |
| `anthropic` | Claude API, pay per use | `export ANTHROPIC_API_KEY=…` (model: `DWG_TAKEOFF_ANTHROPIC_MODEL`) |
| `openai` | OpenAI API, pay per use | `export OPENAI_API_KEY=…` and `DWG_TAKEOFF_OPENAI_MODEL=…` |

`DWG_TAKEOFF_AI=anthropic` (or `openai`) makes another backend the default. Everything else works
without any AI: the catalogue, measuring a plan you write or edit, the ruler, exports.

## 2. Run

```bash
uv run dwg-takeoff serve          # http://127.0.0.1:8765  (--port to change)
```

Drawings in `samples/` (git-ignored) are loaded when the server starts; others can be uploaded
with *Încarcă DWG* or dragged onto the page. The first load of a large drawing takes a few seconds
to a minute (conversion, reading, analysis, then the plan image), in background processes; after
that it opens instantly from the cache in `data/`.

### The demo drawing

`examples/demo-site-plan.dxf` is a small site plan with a legend, a building, a parking lot, curbs
drawn twice, lawns, trees and lamp posts; the expected quantities are listed in
[`examples/make_demo.py`](../examples/make_demo.py).

```bash
DWG_TAKEOFF_SAMPLES=examples uv run dwg-takeoff serve
```

Ask for example *"building footprint, vehicle and sidewalk paving areas, lawn area, curb length,
number of trees and lamp posts, painted area of the parking lines"*. The answer should be 192,
800, 228 and 255 m², 120 m of curb (out of 200 m drawn), 10 trees, 4 lamp posts and 9,60 m².

## 3. From the command line

```bash
uv run dwg-takeoff inspect drawing.dwg          # units (with evidence), legends, tables, site region
uv run dwg-takeoff catalogue drawing.dwg        # the numbered breakdown the AI chooses from
uv run dwg-takeoff ask drawing.dwg "suprafața de pavaj și lungimea bordurilor" --json result.json
```

See [cli.md](cli.md) for every command.

## 4. Next

- [user-guide.md](user-guide.md) — checking an answer, correcting it, adding project information
- [catalogue.md](catalogue.md) — how the drawing is broken down
- [configuration.md](configuration.md) — every setting
