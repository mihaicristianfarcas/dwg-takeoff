# HTTP API

The web UI uses this JSON API; scripts can too. Interactive documentation (OpenAPI) is served at
`/docs` while the app runs. All quantities are in metres; geometry is in model coordinates
(drawing units) as `{"polygons": [[ring, hole…]…], "lines": [[[x, y]…]…], "points": [[x, y]…]}`.

State-changing requests (`POST`, `PUT`, `DELETE`) from another origin are refused (403).

## Drawings

| Method | Path | |
|---|---|---|
| GET | `/api/health` | converter and AI backends: availability and details |
| GET | `/api/projects` | drawings loaded, with their processing status |
| POST | `/api/projects` | upload a `.dwg` / `.dxf` (multipart field `file`); processing starts in the background |
| GET | `/api/projects/{id}` | details; once `status` is `ready`: units and their evidence, site region, legends, sheets, tables, notes, warnings, catalogue size |
| POST | `/api/projects/{id}/units` | `{"code": 4}` (a unit code), `{"scale": 0.1}` (metres per drawing unit) or `{}` (back to the drawing's units); everything is recomputed |
| GET / PUT | `/api/projects/{id}/info` | project notes: `{"notes": "…"}`; GET also lists the reference documents |
| POST | `/api/projects/{id}/references` | add a reference document (multipart `file`: PDF, DWG, DXF, TXT, MD; ≤ 60 MB) |
| DELETE | `/api/projects/{id}/references/{doc}` | remove one |

Unit codes: 6 metres, 4 millimetres, 5 centimetres, 14 decimetres, 2 feet, 1 inches.

## The plan view

| Method | Path | |
|---|---|---|
| GET | `/api/projects/{id}/view[?wait=true]` | URL and model window of the plan image; `202` while it renders (or wait) |
| GET | `/api/projects/{id}/view.png` | the image |
| GET | `/api/projects/{id}/tile/{z}/{i}/{j}.png` | a sharper tile for deep zoom (`z` 1–5; `i` from the left, `j` from the bottom of the window) |
| GET | `/api/projects/{id}/features/{fid}` | one entity: handle, layer, kind, area / length, geometry |
| GET | `/api/projects/{id}/layer?name=L[&pattern=P][&color=#rrggbb][&site=true]` | the entities of a layer, to highlight |

## The catalogue

| Method | Path | |
|---|---|---|
| GET | `/api/projects/{id}/catalogue` | every entry with its evidence, label and category; the categories; which entries the latest analysis used |
| PUT | `/api/projects/{id}/catalogue/label` | `{"key": "<entry key>", "label": "…", "category": "paving"}` — empty label and null category clear it |
| GET | `/api/projects/{id}/entry/{eid}` | the geometry of one entry (placed blocks: what they draw) |

## Analyses

| Method | Path | |
|---|---|---|
| POST | `/api/projects/{id}/ask` | `{"query": "…", "backend": "codex", "effort": "medium", "model": null}` → `{"job": "<id>"}` |
| GET | `/api/jobs/{job}` | status (`running`, `done`, `error`, `cancelled`), stage, progress events, elapsed time, typical time, and the `result` when done |
| POST | `/api/jobs/{job}/cancel` | cancel a running job |
| POST | `/api/projects/{id}/execute` | `{"plan": {…}}` → the measured result, nothing saved (catalogue ids are expanded) |
| POST | `/api/projects/{id}/runs` | `{"plan": {…}, "query": "…", "parent_run": "…"}` → save an edited plan as a new run, with its result |
| GET | `/api/projects/{id}/runs` | the history |
| GET | `/api/projects/{id}/runs/{run}` | a past result, its plan re-measured with the current engine |
| DELETE | `/api/projects/{id}/runs/{run}` | hide it from the history (kept on disk as `_deleted_<run>`) |
| GET | `/api/projects/{id}/runs/{run}/{file}` | `prompt.txt`, `plan.json`, `codex.log`, `digest.json`, `features.csv`, `result.json`, `project_info.txt`, `review_report.txt`, `review.json`, `plan_first.json` |
| POST | `/api/export/xlsx` | `{"result": {…}, "project_name": "…", "project_id": "…"}` → the Excel workbook |

## Result format

```json
{
  "items": [{
    "id": "pavaj_8", "label": "Pavaj 8 cm", "value": 800.0, "unit": "m²",
    "status": "measured", "confidence": "high", "formula": "800,00 m²",
    "reasoning": "…", "assumptions": [], "questions": [], "warnings": [],
    "components": [{
      "label": "…", "measure": "area", "base_value": 800.0, "base_unit": "m²", "factors": [],
      "value": 800.0, "unit": "m²", "formula": "800,00 m²", "n_entities": 1,
      "stats": {"entities": 1, "raw_sum": 800.0, "union": 800.0},
      "evidence": [{"handle": "2A1", "layer": "PAVERS-8CM", "kind": "hatch", "raw": 800.0, "counted": 800.0, "note": "", "at": [24.0, 14.0]}],
      "overlay": {"polygons": […], "lines": [], "points": [], "removed": []},
      "warnings": []
    }]
  }],
  "checks": [{"type": "area_overlap", "items": ["a", "b"], "value": 14.3, "message": "…"}],
  "plan": {…}, "query": "…", "run": "20261015-163812-123456"
}
```
