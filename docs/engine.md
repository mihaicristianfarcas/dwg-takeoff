# The measurement engine

Every number of an answer is computed here, deterministically, from the drawing's geometry —
with the evidence needed to check it. Code: `src/dwg_takeoff/engine/` (`measure.py` for the
measurements, `executor.py` for plans).

## From a component to a value

1. **Select.** Each source (a catalogue entry expands to one or more) selects entities by layer
   (exact, then case-insensitive; unknown layers are reported with similar names), kinds (`hatch`
   includes SOLIDs), pattern, colour, block name, handles, and whether the entity is drawn directly
   or inside a container block. Blocks nested inside other blocks are not counted unless asked for
   by name. Legend samples are never selected. With `region: "site"` only entities whose
   representative point lies inside the site region count. An entity selected by several sources
   counts once.
2. **Measure** with the component's `measure` (below), subtracting `subtract_sources` where the
   measure allows it.
3. **Apply factors**: the value is multiplied by each factor; the resulting unit follows from the
   measure and the factors' units (m² × m = m³). A factor that is not a number is reported.
4. **Report**: value, unit, formula (`1 234,35 m² × 0,08 m (grosime, presupus) = 98,75 m³`),
   statistics, evidence rows, the geometry to draw, warnings.

An item's components are summed when they share a unit; otherwise the item reports the mismatch.

## Measures

| Measure | Result | Method |
|---|---|---|
| `area` | m² | union of the surfaces (fills, closed outlines), overlaps counted once; each entity's *counted* share is what it adds to the larger ones before it. Subtracted surfaces (also setting-out footprints positioned on the plan) are removed from the union |
| `perimeter` | m | boundary of that union (outer and inner rings), shared edges once — formwork = perimeter × height |
| `length` | m | total line length where a piece lying within `tolerance_m` of, and parallel to (± 20°), an already counted line is the same physical element: removes exact duplicates and both faces of a curb, keeps perpendicular joins. Longest lines first. `subtract_sources` here means *already counted elsewhere* (a smaller curb type running along a larger one) |
| `enclosed_area` | m² | area enclosed by lines that close into loops (a lot drawn as separate property lines). Gaps up to `tolerance_m` at free line ends are bridged with short connectors; the drawn geometry is not moved |
| `count` | pcs | number of entities (placed blocks, usually); two of the same block at the same position count once. Counting texts is flagged: a number read from a label is not a measurement |
| `count_groups` | pcs | symbols drawn without blocks (stairs as lines, exploded trees): geometry closer than `tolerance_m` forms one group; each group is outlined on the plan with its size |
| `strip_area` | m² | painted area of polylines with a constant width (road markings): centre-line × drawn width, overlaps once |

Default tolerances: 0.30 m for `length` and `count_groups`, 0.05 m for `enclosed_area`. For curbs,
use the element's width plus 5 cm (0.25–0.30 m for a 20 cm curb).

### Setting-out footprints

Tables of setting-out coordinates (objects listed by corner points, in the national grid) are read
from the drawing. When their points coincide with drawn vertices, the tables are georeferenced
(`cad/georef.py`: a similarity transform found by RANSAC on point pairs of equal length, axes
swapped if needed). A footprint can then be measured like a drawn outline, drawn on the plan, and
subtracted from areas. Without georeferencing its area still counts (from the table's own
coordinates), but it cannot be located or subtracted — the result says so.

## Evidence

Each component returns one evidence row per entity: AutoCAD handle (the top-level INSERT's handle
for geometry inside blocks), layer, kind, pattern, block, colour, visibility, its own value (*raw*)
and the value actually *counted*, and a note when they differ ("duplicate of an entity already
counted", "70 % already counted", "includes a trace counted elsewhere"). The statistics give the
drawn sum against the counted value. Entities on frozen or off layers are measured and flagged.

## Cross-checks

After all items are measured, every pair of components with the same measure and unit is checked:

- **areas** that overlap by more than 0.5 m² — the same surface in two items (or twice in one);
- **lengths** whose joint de-duplicated length is shorter than their sum by more than 0.5 m — the
  same curb counted twice.

Overlaps between different kinds of quantity (a paving area and the concrete volume under it) are
expected and not reported.

## Re-measuring

Plans keep their filters, so any saved plan can be measured again: opening a past run in the UI
re-measures it with the current engine, `POST /api/projects/{id}/execute` measures an edited plan,
`dwg-takeoff ask FILE "…" --plan plan.json` measures a plan file (catalogue ids are expanded first).
