# How it works

## Principles

1. **The AI never computes a quantity.** It reads a factual summary of the drawing and returns a
   *plan*: which catalogue entries (or filters) to measure, how, with which factors. A
   deterministic engine produces every number.
2. **Every number is verifiable.** It comes with the entities it was measured on (AutoCAD handles),
   the value each one contributed after de-duplication and why, the formula, where each factor
   comes from, and the geometry on the plan.
3. **Facts first, judgement second.** Everything that can be established without judgement —
   units, the site region, legends, what each group of entities measures, which entries draw the
   same surface, room numbers joined to schedules — is computed before the AI sees the drawing,
   and shown with its evidence.
4. **Assumptions are explicit.** An assumed thickness is marked *assumed*, can be edited, and comes
   with a question for the client.

## The pipeline

```
           cad/                         analysis/                     ai/                  engine/
DWG ──convert──▶ DXF ──extract──▶ Drawing ──▶ site region ──▶ catalogue ──▶ digest ──▶ plan ──▶ measurements
                                    │          (viewports)    (entries,     (prompt     (JSON)   + evidence
                                    │                          relations)    text)        ▲          │
                                    └── units, legends, sheets, tables, georef            │          ▼
                                                                                   review ◀── report of what
                                                                                   (corrected plan)  was measured
```

| Stage | Package | What it does |
|---|---|---|
| Convert | `cad/convert.py` | DWG → DXF with the ODA File Converter (one at a time, cached by file hash) |
| Extract | `cad/` | DXF → `Drawing`: every entity as shapely geometry with its effective layer, colour and visibility; blocks exploded recursively and placed where they are drawn; layers; legends; sheets and viewports; tables; callouts and dimensions; units |
| Georeference | `cad/georef.py` | setting-out coordinate tables matched to drawn vertices (RANSAC similarity transform), so footprints listed only in tables can be located on the plan |
| Site region | `analysis/site.py` | the model window shown by the most detailed, most repeated sheet viewports |
| Catalogue | `analysis/catalogue/` | the numbered breakdown of everything measurable, measured and linked to the drawing's own names ([catalogue.md](catalogue.md)) |
| Digest | `analysis/digest.py` | the factual summary sent to the AI: sheets, legends, tables, notes, texts, then the catalogue |
| Plan | `ai/` | the chosen backend turns request + digest into a plan; catalogue ids are expanded into filters; the plan is checked against the drawing ([ai.md](ai.md)) |
| Measure | `engine/` | each component's entities are selected and measured; factors applied; cross-checks ([engine.md](engine.md)) |
| Review | `ai/review.py` | the AI sees what its plan measured and confirms it or corrects items |
| Present | `web/`, `cli.py`, `export.py` | the web UI, the CLI, the Excel workbook |

## Code layout

```
src/dwg_takeoff/
  cad/            reading drawings
    convert.py      DWG -> DXF (ODA File Converter), cache folders, file sniffing
    model.py        the Drawing data model (Feature, LayerInfo, LegendEntry, EmbeddedTable...)
    entities.py     one entity: effective colour, geometry (hatches, polylines, arcs...), texts
    modelspace.py   model space -> features; blocks exploded and placed; callouts, dimensions
    legends.py      legend swatches + labels, on sheets and in model space
    sheets.py       layouts: titles, notes, viewports and their plot scale
    tables.py       OLE Excel/Word tables, AutoCAD tables, tables drawn as text, setting-out footprints
    units.py        drawing units and the evidence for them
    extract.py      the entry point: DXF -> Drawing
    georef.py       setting-out tables -> model space
    render.py       the plan image and zoom tiles (ezdxf + matplotlib)
  analysis/       understanding the drawing
    site.py         the site region
    colors.py       colour names ("dark green")
    vocabulary.py   English construction vocabulary + US National CAD Standard layer codes
    catalogue/      entry.py, build.py, relations.py, labels.py, text.py, expand.py
    digest.py       the AI's view of the drawing
  engine/         measuring
    measure.py      area unions, de-duplicated lengths, enclosed areas, groups, counts, stripes
    executor.py     plan -> values, formulas, evidence, overlays, cross-checks
    geojson.py      geometry for the viewer
  ai/             planning
    __init__.py     backend registry      planner.py   make_plan: plan -> validate -> review
    prompt.py       rules + catalogue guide          schema.py    the plan's JSON schema
    request.py      request, events, cancellation   validation.py ids -> filters, plan checks
    review.py       measurement report, review schema, merging corrections
    tools.py        lookup tools of the API backends
    codex_cli.py · anthropic_api.py · openai_api.py
    skills/dwg-catalogue/SKILL.md   how to read the catalogue (sent with every prompt)
  web/            the web app
    __init__.py     FastAPI app, same-origin guard, routers, static files
    routes/         projects · viewer · catalogue · analysis · runs
    views.py        background image and tiles      jobs.py   AI jobs and their progress
    static/         index.html, style.css, js/*.js (ES modules, no build step)
  store.py        projects: load once, cache on disk, units override, worker processes
  project_info.py notes and reference documents per drawing
  export.py       Excel workbook
  formatting.py   number formats       config.py   every setting (environment variables)
  cli.py          the dwg-takeoff command
```

## The data model

`cad.model.Drawing` is what everything downstream works on:

- `features` — one `Feature` per measurable entity: `kind` (`hatch`, `solid`, `closed`, `line`,
  `block`, `text`), shapely `geom` in drawing units, `layer`, effective `color` (`#rrggbb`; BYLAYER
  and BYBLOCK resolved through nested blocks), `pattern`, `block`, `visible` (layer on and not
  frozen), `width` (constant polyline width), `attribs`, `text`. Entities inside blocks are
  `nested` and keep the **handle of the top-level INSERT**, so an AutoCAD selection finds them.
- `layers`, `legends`, `layouts` (sheets with viewports), `tables` (embedded / AutoCAD tables with
  setting-out objects), `text_tables`, `callouts`, `dimensions`, `block_descriptions`.
- `unit_scale` (metres per drawing unit) and `unit_info` (source, confidence, evidence).
- `legend_handles` — swatches of legends drawn in model space: samples, never measured.

Quantities are computed in drawing units and converted with `unit_scale` at the end, so changing
the units recomputes everything without re-reading the drawing.

## Projects, caching and the data folder

`store.Store` loads each drawing once (keyed by the SHA-256 of the file) and keeps it in memory.
Everything about a drawing lives in `data/cache/<hash>/`:

```
drawing-oda.dxf          converted DXF (DWG input)
drawing-v<N>.pkl         extraction + digest cache (Drawing, digest, table transform)
view-v<N>.png/.json      the plan image and its model window;  tiles-v<N>-*/  zoom tiles
labels.json              the user's catalogue labels          units.json   units override
project_info.txt         notes                                 references/  documents + extracted text
runs/<timestamp>/        one folder per analysis:
    prompt.txt digest.json catalogue.csv features.csv schema.json   what the AI got
    codex.jsonl codex.log / api.jsonl                               what it did
    plan_first.json review_report.txt review.json                   the review
    plan.json result.json project_info.txt                          the answer
```

`<N>` is `store.PIPELINE_VERSION`: bump it whenever extraction, the digest or the catalogue change
what they produce (or a pickled class moves), and cached drawings are rebuilt on their next load.
Uploads go to `data/uploads/`. The location is `DWG_TAKEOFF_DATA` ([configuration.md](configuration.md)).

## Processes and threads

The web server runs conversion, extraction and rendering in a small process pool (they are
CPU-bound pure Python), so requests stay responsive; AI jobs run in threads and report progress
events that the UI polls. The ODA converter runs one conversion at a time, also across processes
(a file lock). Cache files and renders are written atomically, so the CLI and the server can share
the data folder. `DWG_TAKEOFF_INPROCESS=1` runs everything in one process (tests).

## The web app

The UI is plain HTML, CSS and ES modules served by FastAPI — no build step, no framework. It talks
to the JSON API in [web-api.md](web-api.md). The server listens on localhost and refuses
state-changing requests from other origins ([../SECURITY.md](../SECURITY.md)).
