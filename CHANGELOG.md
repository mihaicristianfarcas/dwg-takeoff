# Changelog

All notable changes are listed here; the project follows [semantic versioning](https://semver.org/).

## 0.1.0 — unreleased

First public version.

- Read DWG (via the ODA File Converter) and DXF into a measurable model: nested and dynamic blocks
  placed where they are drawn, hatches with islands, true colours, legends on sheets and in model
  space, embedded / AutoCAD / text tables, setting-out tables georeferenced onto the plan, units
  checked against dimensions and objects of known size.
- The element catalogue: a numbered, measured breakdown of every drawing with names from legends,
  callouts, texts and room schedules, duplicates, fills edged by lines, an English vocabulary of
  categories, and editable labels remembered per drawing.
- AI planning with the Codex CLI (ChatGPT subscription), the Claude API or the OpenAI API: the model
  chooses catalogue entries, measures and factors; plans are validated against the drawing and
  reviewed by the model after measurement.
- The measurement engine: area unions, de-duplicated lengths, perimeters, enclosed areas, counts,
  symbol groups, painted stripes, setting-out footprints; per-entity evidence and double-counting
  checks.
- Web app: plan viewer with zoom tiles and ruler (with unit calibration), progress timeline,
  results with evidence and AutoCAD selection snippets, editing without the AI, project information
  and reference documents, catalogue explorer, history, Excel export with live formulas.
- CLI (`serve`, `inspect`, `digest`, `catalogue`, `ask`, `install-skill`), the `dwg-catalogue` agent
  skill, a demo drawing, documentation.
