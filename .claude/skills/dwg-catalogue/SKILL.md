---
name: dwg-catalogue
description: >-
  How to read the element catalogue of a CAD drawing in DWG Takeoff and turn a quantity-takeoff
  request into catalogue entry ids. Use whenever a prompt or file contains a CATALOGUE (lines such
  as "S8 'layer' SOLID grey ×2 376.12 m² | ..."), a catalogue.csv, or when measuring areas,
  lengths or counts of a DWG/DXF drawing in this project.
---

# Reading the element catalogue

The catalogue is the deterministic breakdown of one drawing: every group of entities the geometry
engine can measure, numbered, already measured, with every name the drawing itself gives it.
Choosing an entry *is* choosing an exact engine selection (its layer, pattern, colour, block,
inside/outside blocks). You decide WHAT to measure and HOW; the engine measures it. Never
compute, estimate or copy a quantity yourself.

## Entry ids

| id | entry | measured as | use for |
|---|---|---|---|
| `S12` | fills (hatch / solid) of one layer + pattern (+ colour if the layer uses several) | area m² | surfaces: paving, lawn, roofs, buildings |
| `O5` | closed outlines (polylines, circles) of one layer (+ colour) | area m², perimeter | surfaces drawn as outlines, building footprints, formwork perimeters |
| `L3` | lines of one layer (+ colour), closed outlines included | length m | curbs, fences, walls, pipes, boundaries, markings |
| `B2` | placed blocks of one name on one layer (+ colour) | count | trees, doors, lamps, signs, cars, furniture |
| `N4` | blocks of one name inside other blocks | count | doors inside a building block, trees in a "row" block |
| `T1` | footprint of an object of a setting-out table (coordinates) | area m², perimeter | foundations, pads, buildings listed by coordinates |
| `O2.3` | one surface of `O2` that has a name of its own | area m² | one room, one zone |

## Line format

```
S8 'drum-pavele-trafic-mediu' SOLID grey ×2 412.50 m² HIDDEN | "Drumuri și platforme" (legend) | =paving | legend "…" | callout "…" | texts "…" | dims "…" | attr TAG=v1/v2 | layer: description | dup ≈O4 ⊃O9 | edged by L3 'borduri' 71%
  S8.1 one surface 251.10 m² | "label" | =category
```

* `'layer'` then pattern and colour name (when they distinguish the entry); `inside block 'X'`:
  the entry is content of a block that holds a whole drawing (survey, building, playground);
  `N` lines name the counted block; `'name'` after the layer of a `B` line is the block name.
* `×N` entities inside the site region; `(+M outside site)`; `×N all OUTSIDE site` (legends,
  details, other sheets drawn in model space - rarely part of a takeoff).
* Quantity: area for S / O / T / parts (union: overlaps counted once); length for L, with
  "(X m without duplicate traces)" when the same line is drawn twice; for B / N the count is `×N`;
  `symbol 1.2 m` = drawn size of the block; `width 0.12 m` = constant polyline width (stripes).
  All values are metres, inside the site region (whole drawing when there is none).
* `HIDDEN`: on a frozen / off layer. It may still be what the legend names.
* `"label" (source)`: the entry's name. Sources, most to least reliable: `(user)` confirmed by
  the user - follow it; `(legend)` the designer's legend swatch matches it; `(callout)` a leader
  points at this block; `(text)` the only text written inside the surface.
* `=category`: what the English vocabulary infers from names (curb, paving, tree, room...).
  `=x (user)` is confirmed; otherwise a hint: no category does not mean irrelevant (non-English
  names get none).
* Evidence: `legend` other legend labels on the same swatch (several labels = the legend uses one
  sample for several things: ask which); `callout` texts of leaders pointing at it (on lines and
  surfaces they may describe something drawn alongside, e.g. a conduit along a curb); `texts`
  written inside (room numbers joined with the schedule appear as "106 KITCHEN (schedule 13.44
  m²)"; object codes of a setting-out list mark positions, they do not name the surface); `dims`
  dimension values written on it; `attr` block attribute values; descriptions of layer / block.
  A room code missing from the schedule shows as `"209 (not in the schedule)"`, or as
  `"209 BEDROOM (schedule row 205, 16.94 m²)"` when exactly one schedule row that no other room
  took fits its area (a numbering error in the drawing or the schedule): measure the room, say so.
* `dup`: the same surface is drawn by another entry: `=` same surface, `⊂` inside it, `⊃`
  contains it, `≈` mostly overlaps.
* `edged by L6 'wall' "Building" 82%`: 82% of this surface's boundary runs along the lines of L6
  (with L6's legend label). The lines draw the element - with its details: wall thickness,
  openings, steps - and this fill is its area. On a line entry the reverse reads `edges S4 82%`.
* Not every entry is shown in the prompt: search `catalogue.csv` (Codex) or call
  `catalogue_search` (API) for the rest - minor entries, content outside the site.

Already handled by the engine, do not correct for it: legend swatches drawn in model space are
excluded from every quantity; blocks are located where they are drawn (not at a far-away
insertion point); coincident duplicate lines are merged in L lengths.

## From request to plan

1. One item per requested quantity, in the client's order and language.
2. Find the entries: legend labels and (user) labels first, then callouts, texts, layer / block
   names, categories. Search the CSV / tool for words of the request when the prompt list does
   not show a good candidate.
3. Pick ONE representation per physical surface: when entries are `dup =` / `≈`, choose the fill
   the legend names (else the fill over the outline) and say which duplicates you ignored. Never
   put both of a `=` pair in one item or in two items of the same kind.
4. Measure by kind:
   * area: S, O, T, or a part (`O2.3`). An element whose legend or name points at lines (walls,
     curbs) is measured by the fill `edged by` them; only when no surface is edged by them,
     `enclosed_area` on the L entry (tolerance_m = gap to close, e.g. 0.05) - it also encloses
     every detail the lines draw, so check the result against the drawing's other surfaces.
   * length: L, tolerance_m ≈ element width + 0.05 m (merges the two drawn faces of a curb).
   * perimeter: O / S / T (formwork = perimeter × height).
   * count: B / N. Symbols drawn as loose lines: `count_groups` on their L entry.
   * painted area of stripes: `strip_area` on an L entry with a width.
5. `entries` / `subtract_entries` take the ids; leave `sources` / `subtract_sources` empty.
   Raw filters only when no entry fits (e.g. a few handles of an entry); never invent ids.
6. `region: "site"` unless the requested element lies outside the site region; `null` when the
   drawing has no site region.
7. A block in several colours is several entries (often several species / types - the legend
   says which); count each wanted one. Several legend labels on one entry: count it once and ask
   how to split.
8. Rooms: use the named part (`O2.3`). The measured area is the answer; a schedule area that
   differs is reported as a cross-check, never used instead. Two codes in one outline ("106
   KITCHEN + 105 DINING") mean the rooms are drawn as one surface: measure it, say so, quote the
   schedule split.
9. Unsure between entries: take the plausible ones, lower the confidence, and ask a question
   naming each left-out candidate with its id and size ("S5 SOLID orange ×103, 12.10 m² - also
   wood planks?").
10. Cite in `reasoning`: name in the drawing -> entry id -> what is measured.

## Examples (illustrations from another drawing: ids and names differ in yours)

Request "paving for vehicles, 8 cm" with `S4 'ROAD-PAVERS' SOLID grey ×3 820.00 m² | "Vehicle
paving" (legend) | dup =S9` and `S9 'ROAD-PAVERS-OLD' ANSI37 grey ×3 820.00 m² HIDDEN`:

```json
{"label": "Vehicle paving", "measure": "area", "entries": ["S4"], "subtract_entries": [],
 "sources": [], "subtract_sources": [], "region": "site", "tolerance_m": null, "factors": []}
```
reasoning: "Legend 'Vehicle paving' -> S4; S9 is a hidden copy of the same surface, ignored."

Curbs of two types, the larger one subtracted from the smaller (shared traces counted once):
`{"measure": "length", "entries": ["L7"], "subtract_entries": ["L2"], "tolerance_m": 0.15, ...}`
for the 10x15 curb next to `{"measure": "length", "entries": ["L2"], "tolerance_m": 0.25, ...}`
for the 20x25 curb.

Trees: `B3 'PLANTING' green 'TREE-A' ×40 | "Pine" (legend) | legend "Thuja"` -> count B3 and
ask: "B3 (40) is both Pine and Thuja in the legend - how are they split?"

<!-- planner-guide-end -->

## Working with this repository (interactive agents)

The app builds the catalogue in `src/dwg_takeoff/analysis/catalogue/` (entries in `build.py`,
evidence and relations in `relations.py`, the line format in `text.py`; vocabulary in
`src/dwg_takeoff/analysis/vocabulary.py`) and sends the guide above to the planning AI
(`src/dwg_takeoff/ai/prompt.py`). docs/catalogue.md explains how every field is derived.

* Show a drawing's catalogue: `uv run dwg-takeoff catalogue FILE.dwg` (`--all` every entry,
  `--search "curb"` matching entries, `--entry S8` one entry with its filters and evidence,
  `--csv out.csv`).
* Measure a plan written with entry ids: save it as JSON (`{"items": [...]}` with components as
  above) and run `uv run dwg-takeoff ask FILE.dwg "request" --plan plan.json` - the ids are
  expanded and the engine prints every quantity with its formula and entities.
* Labels confirmed by the user live in `data/cache/<drawing id>/labels.json` (edited in the web UI,
  *Explorare planșă → Catalogul planșei*, or `PUT /api/projects/<id>/catalogue/label`).
* Entry ids are only stable for one processing of a drawing; plans store the filters the ids
  expand to, so saved analyses keep working.
* This file is the source of truth: `src/dwg_takeoff/ai/skills/dwg-catalogue/SKILL.md`. After
  editing it, run `uv run dwg-takeoff install-skill` to refresh the copies in `.claude/skills/`
  (Claude Code) and `.agents/skills/` (Codex).
