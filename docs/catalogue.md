# The element catalogue

The catalogue is the deterministic step between reading a drawing and asking the AI. It breaks the
drawing into a numbered list of everything the engine can measure, measures each entry, and
attaches every name the drawing gives it. The AI then answers by choosing entry ids.

Why: with raw layer lists the model had to guess which hatch was which, misspell layer names and
recompute relations on every request. With the catalogue it sees facts — *"S8: 376 m² of SOLID
grey on this layer, the legend calls it 'Roads and platforms', the same surface is also drawn as
O4"* — and picks. Answers got shorter, faster and more consistent (see [evaluation.md](evaluation.md)).

Code: `src/dwg_takeoff/analysis/catalogue/`. The AI-facing description of the format is the
[`dwg-catalogue` skill](../src/dwg_takeoff/ai/skills/dwg-catalogue/SKILL.md).

## Entries

Each entry is exactly what one engine filter selects, so choosing an entry *is* choosing a source.

| Id | Kind | Grouping | Measured |
|---|---|---|---|
| `S12` | `surface` | fills (HATCH, SOLID, MPOLYGON) of one layer + pattern | area |
| `O5` | `outline` | closed polylines / circles / closed splines of one layer | area, perimeter |
| `L3` | `linear` | lines of one layer, closed outlines included | length |
| `B2` | `block` | placed blocks of one name on one layer | count |
| `N4` | `nested_block` | blocks of one name inside other blocks (≥ 3 of them) | count |
| `T1` | `table` | the footprint of one object of a setting-out table | area |
| `O2.3` | `part` | one surface of `O2` that has a name of its own (a room) | area |

- **Colour** splits a group only when the layer really uses several colours (drawings with
  everything on layer 0, or one block in several colours — often several species / types).
  A single colour is not part of the filter, so the entry still matches if the layer colour changes.
- **Containers**: a placed block that draws more than 15 m (largest side), or ≥ 8 m with at least
  2 000 parts, holds a drawing (a survey, a building, a playground) rather than a symbol. Its
  content becomes entries of its own (`inside block 'X'`); smaller blocks stay countable symbols.
- **Legend samples** — the swatches of a legend drawn in model space — are left out of every entry
  and every measurement.

Entry ids are numbered per kind, most relevant first: inside the site region before outside,
drawn directly before inside containers, larger before smaller. Ids are stable for one processing
of a drawing; each entry also has a stable **key** (`kind|layer|pattern|colour|block|container`)
under which labels are stored.

## Quantities

All quantities are in metres, **inside the site region** when the drawing has one (the model window
of its detailed sheets — see [architecture.md](architecture.md)), with the count of entities inside
and outside it.

- Surfaces and outlines: area of the **union** (overlaps counted once); outlines also perimeter.
- Lines: drawn length, and — when the same trace is drawn more than once — the length *without
  duplicate traces* (coincident pieces within 5 cm merged).
- Wide polylines: the drawn stripe width (road markings).
- Blocks: the count; the drawn size of the symbol (median largest side, robust to stray parts);
  up to 8 attribute tags with sample values.

## What the drawing says about an entry

Each relation is computed without judgement and shown as evidence.

### Legend labels

A legend entry (a swatch with its label to the right, on a sheet or in model space) links to the
entries on the swatch's layer with the same pattern, and the same colour when the layer is split by
colour. A hatch swatch prefers fill entries; a line sample prefers line entries. A swatch that is
an **empty outline** (e.g. "Building" drawn as a rectangle on the walls' layer) shows how the
element is drawn, so it links to that layer's outlines *and* lines.

### Texts written inside

A text that names something (at least two letters) and lies inside a surface names the smallest
such surface — the room, not the floor. Tag boxes drawn around a room number are skipped: a surface
must be at least 30 text-heights² in area. A surface holding more than 4 names is a sheet frame
or a zone with notes, not a named surface.

### Room schedules

Codes written inside surfaces (`104`, `1.04`, `A12`) are looked up in tables that list
*code, name, area* — room schedules, lists of objects; embedded, AutoCAD or drawn as text.

- A code names the surface when the scheduled area fits it: within 30 % for one code, within 15 %
  for the sum of several codes in one outline (*"106 KITCHEN (schedule 13.44 m²) + 105 DINING
  (schedule 15.68 m²)"* on a 29.12 m² outline). A code listed twice picks the row whose area fits.
- A schedule area that does not fit is shown as text, not as a name (setting-out object codes
  written on a paving mark positions, they do not name the paving).
- A code missing from the schedule (a numbering error) is kept: named by the one schedule row that
  no other room took and whose area fits within 2 % — *"209 BEDROOM (schedule row 205, 16.94 m²)"* —
  or shown as *"209 (not in the schedule)"*.

Named surfaces become **parts** (`O2.3`), so one room can be chosen without handles.

### Callouts

The arrow of a LEADER / MULTILEADER (also inside blocks) names what it touches: a line within a
third of a text height, else a symbol whose drawing contains the tip, else the smallest surface
under it. Leaders without text take the nearest text. Only callouts on **symbols** become labels;
on lines and surfaces they are information (a conduit's callout often points at the curb it runs
along).

### Dimensions

Linear, aligned, radius and diameter dimensions whose text lies inside a surface are listed on it.

### Duplicates

Entries drawing (nearly) the same surface — a fill and its outline, a frozen copy, the same zone on
two layers: `=` same surface (overlap > 90 % of the union), `⊂` inside / `⊃` contains (> 90 % of the
smaller, at most 1.5× its size), `≈` mostly overlaps (> 50 %, at most 2×). A small surface inside a
big one is not a duplicate.

### Edges

A fill whose boundary runs along the lines of another layer — a building hatch inside its walls, a
pavement between its curbs — is *edged by* that line entry: `edged by L6 'wall' "Building" 75%`
means 75 % of the fill's boundary lies within half a metre of L6's lines (within a tenth of the
fill's typical piece size for small pieces). The lines draw the element, with its details; the fill
is its area. Only real surfaces are checked (≥ 20 m² in all, pieces ≥ 4 m²) and only shares of at
least 50 % are kept. The line entry shows the reverse: `edges S4 75%`.

### Category

An English vocabulary (`analysis/vocabulary.py`, ~30 categories: building, room, wall, door, road,
parking, paving, curb, lawn, planting, tree, shrub, fence, marking, drainage, utility…, each with
the measure it implies) classifies the entry from its names. Words are normalised (lower case,
camelCase and digits split, plurals); phrases match longest first; US National CAD Standard layer
codes (`C-ROAD-CURB`, `L-PLNT-TREE`) are read by group. The **last** term of a name is its head
("concrete curb" is a curb) and counts fully, earlier terms half. Sources weigh differently:

| Source | Weight |
|---|---|
| the user's label | 10 |
| legend label | 4 |
| callout | 3.5 |
| layer / block description | 3 |
| layer name, block name | 2.5 |
| attribute value | 2 |
| text written inside | 1.5 |

A category needs a score of at least 2 — a word in a note alone is not enough. Names in other
languages get no category; they are still shown, and the AI reads them.

### Labels

The label shown for an entry is, in order: the user's label, the legend label, the callout on a
symbol, the only text written inside. Labels and categories set in the UI are stored per drawing
in `labels.json` by entry key; they survive re-extraction, appear as `(user)` in the next prompt
and outweigh everything else.

## The prompt line

```
S8 'drum-pavele-trafic-mediu' SOLID grey ×2 412.50 m² HIDDEN | "Drumuri și platforme" (legend) | =paving | texts "…" | dup ≈O4 ⊃O9 | edged by L3 'borduri' 71%
  S8.1 one surface 251.10 m² | "label" | =category
```

id, layer, pattern / colour / block, count (`×N`, `(+M outside site)`, `all OUTSIDE site`),
quantity, `HIDDEN` (frozen or off layer), then the evidence: label with its source, category,
legend, callouts, texts, dimensions, attributes, descriptions, duplicates, edges. The prompt shows
the 300 most relevant entries (inside the site and named first); every entry is in `catalogue.csv`
(Codex) and reachable with the `catalogue_search` tool (API backends).

## From ids to measurements

A plan component lists `entries` and `subtract_entries`. Before measuring, `expand_entries` adds
each entry's filters to the component's `sources` (marked with the entry id and key). The plan
keeps the filters, so it can be measured again — later, after a re-extraction, or by the CLI —
without the catalogue. Unknown ids are reported to the model, which gets one chance to fix them.

## Using it

- Web UI: *Explorare planșă → Catalogul planșei* ([user-guide.md](user-guide.md)).
- CLI: `dwg-takeoff catalogue FILE` (`--all`, `--search curb`, `--entry S8`, `--csv out.csv`).
- API: `GET /api/projects/{id}/catalogue`, `PUT /api/projects/{id}/catalogue/label`,
  `GET /api/projects/{id}/entry/{eid}` ([web-api.md](web-api.md)).
