# Evaluation

What was tested, how, and with what results. The AI results below are from the Codex backend
(effort *normală*, with the review pass) in October 2026; your numbers will differ with other
models.

## The drawings

Besides real project drawings (not in the repository), the app was developed against 37 public
drawings: site, landscape, parking, urban and garden plans from free CAD libraries (in metres and in
millimetres, some saved in the wrong units), house, apartment and hotel floor plans with dynamic
blocks, a US lot plan in feet, AutoCAD test files from R11/R12 to 2018 (the LibreDWG test corpus),
drawings made directly on a sheet and empty ones — plus 4 broken downloads (an HTML page saved as
`.dwg`, files without an AutoCAD signature), which are reported as such. All drawings load, and the
viewer shows each correctly.

The repository's own [demo drawing](../examples/demo-site-plan.dxf) has known quantities and is
answered exactly (192 / 800 / 228 / 255 m², 120 m of curb out of 200 m drawn, 10 trees, 4 lamp
posts, 9,60 m² of paint; 40 s including the review).

## Takeoffs on public drawings

| Drawing | Request | Result |
|---|---|---|
| two-storey house, floor plans | living room, kitchen, each bedroom, doors | rooms named through the drawing's room schedule and equal to it (39,01, 16,06, 16,14 … m²); the kitchen measured together with the dining room (one outline, said so, schedule split quoted); a bedroom the schedule lists under a wrong number found through the unmatched schedule row; 15 doors |
| landscape design of a school (metres saved as millimetres) | buildings, paving by type, fences, trees | buildings 8 226 m² — the hatch edged by the walls the legend calls "Building", not the 2 408 m² enclosed by the wall lines; paving per legend type; fences 2 357 m; trees from the legend's species blocks, uncertain plant symbols asked about by id and size |
| garden site plan, no legend, everything on layer 0 | houses, wood decks, stone paving, trees | houses 55,64 m² (dark grey fills), wood 21 m² (orange fills), stone from the GRAVEL hatches, 35 trees (19 of them with their base point 40 m away from the symbol); the uncertain fills and blocks asked about |
| US lot plan, feet (English request) | lot area, property lines, buildable area | 532,95 m², 96,66 m, 302,32 m² — lines closed into areas with `enclosed_area` |
| underground car park | footprint, outer wall, lifts and stairs | 14 081 m², 536,53 m; 16 stair cores counted as groups of loose lines |
| garden design plan | trees by species, shrubs | 37 pines, 96 deciduous trees, 22 shrubs (block counts) |

The review pass caught, among others: wood fills a first plan had missed on the garden plan
(8,84 → 20,95 m²), buildings counted again inside the school's paving, and — on a plan made by a
weaker model — paving reported in m³, a concrete volume in m⁴ and a misspelled layer.

## The catalogue, before and after

The same requests, before the element catalogue and after it (Codex, *normală*, with review):

| Drawing | Time | Uncached input tokens | Output tokens | Answers |
|---|---|---|---|---|
| house | 90 → 57 s | 83 k → 55 k | 3,5 k → 2,2 k | same; five rooms from medium to high confidence |
| garden | 147 → 73 s | 72 k → 63 k | 5,5 k → 2,5 k | same |
| school | 250 → 132 s | 121 k → 71 k | 9,8 k → 4,4 k | buildings right with higher confidence; paving no longer counts the buildings |

Two of the catalogue's rules came from these runs: room numbers missing from a schedule (the house),
and fills edged by the lines a legend names (the school).

## Processing time

Cold, on an Apple-silicon Mac (conversion, reading + extraction, site region + catalogue + digest):

| Drawing | Entities | Convert | Extract | Analyse |
|---|---|---|---|---|
| school landscape | 266 530 | 0,8 s | 6,9 s | 0,7 s |
| hotel ground floor | 156 005 | 2,2 s | 9,1 s | 3,1 s |
| garden site plan | 39 088 | 0,8 s | 1,8 s | 3,0 s |
| family house | 19 668 | 0,7 s | 5,2 s | 0,3 s |
| city plan | 16 426 | 0,6 s | 1,5 s | 1,0 s |

The plan image (5000 px) renders in 1–25 s in a background process; everything is cached. An AI
answer takes ~40 s on a small drawing and 1–4 min on large ones, almost all of it the model writing
the plan. High effort gave the same quantities with 30–60 % more time; a smaller model was four times
faster but made unit errors — the defaults favour quality.

## How changes are checked

- **Unit and integration tests** (`uv run pytest`): geometry rules on synthetic shapes, an
  end-to-end pipeline on a drawing whose quantities are known by construction (in millimetres),
  the catalogue's relations, units, legends, tables, the AI backends against a fake `codex`
  executable and fake API clients, the review pass, the HTTP API, the CLI.
- **Browser tests** (Playwright: Chromium, Firefox, WebKit) of the main flows, opt-in.
- **Private regression drawings**: `tests/test_private_samples.py` measures pinned plans of your own
  drawings kept in `samples/` (see [development.md](development.md)).
- **Golden snapshots** for refactors: `scripts/snapshot.py` records everything the pipeline computes
  for a folder of drawings — the digest text, the catalogue, every entry measured every way, every
  saved plan — and `scripts/compare_snapshots.py` lists every difference. The restructuring of the
  code for the public release changed no number on any of the drawings above; the only intended
  change, a fix of `enclosed_area`, was reviewed value by value (it also stopped the old snapping
  from running out of memory on four of them).
