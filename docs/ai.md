# The AI planner

The AI's job is narrow: read a factual summary of the drawing and the client's request, and return
a **plan** — which catalogue entries to measure for each requested quantity, how, with which
factors, and what it assumed or needs to ask. It never writes a quantity.

Code: `src/dwg_takeoff/ai/`. Entry point: `ai.planner.make_plan`.

## Backends

| Name | Model access | Lookups while planning | Notes |
|---|---|---|---|
| `codex` (default) | the Codex CLI (`codex exec`) with the user's ChatGPT subscription | a read-only shell in the run folder: `catalogue.csv`, `features.csv`, `digest.json` | runs with a lean config (`--ignore-user-config`: no plugins, MCP servers or installed-skills list); the model is the one in `~/.codex/config.toml` unless `DWG_TAKEOFF_CODEX_MODEL` is set |
| `anthropic` | the Claude Messages API (`ANTHROPIC_API_KEY`) | tools: `catalogue_search`, `layer_entities`, `search_texts`, `entities_near` | adaptive thinking (summaries feed the progress view), structured output, the digest in a cached system block, server-side refusal fallback |
| `openai` | the OpenAI Responses API (`OPENAI_API_KEY`) | the same tools, as strict function calls | structured output, a stable prompt-cache key per drawing, reasoning summaries |

All three get the same instructions and the same JSON schema, and are measured by the same engine,
so they are interchangeable per request. A backend is a module with `status()`, `plan(req)` and
`review(req, plan, report)`, registered in `ai/__init__.py`.

## The prompt

```
RULES            the job: quantity surveyor, one item per requested quantity, how to treat
                 duplicates, linear elements, factors (drawing / document / assumed), foundations,
                 counts, what not to do (ai/prompt.py)
CATALOGUE GUIDE  how to read the catalogue and go from a request to entry ids - the planner part
                 of the dwg-catalogue skill (ai/skills/dwg-catalogue/SKILL.md)
DRAWING DIGEST   units and their evidence, sheets and viewports, legends not linked to entries,
                 tables (with georeferenced footprints), notes, other texts, then the CATALOGUE
                 (analysis/digest.py)
PROJECT INFORMATION   the user's notes and reference documents, when there are any
CLIENT REQUEST
```

Everything before the request is identical for every question on the same drawing, so it is
served from the provider's prompt cache after the first one.

The skill file is the single source for how to read the catalogue: the app sends its planner part
with every request, and the same file is installed for interactive agents (Claude Code in
`.claude/skills/`, Codex in `.agents/skills/`; `dwg-takeoff install-skill` refreshes the copies).

## The plan

The answer is constrained to `ai/schema.py:PLAN_SCHEMA` (strict structured output):

```json
{
  "language": "ro",
  "summary": "…",
  "items": [{
    "id": "pavaj_8", "label": "Pavaj 8 cm", "request_text": "pavaj de 8 cm", "unit": "m²",
    "status": "assumption_based", "confidence": "medium",
    "reasoning": "Legend 'Vehicle pavers 8 cm' -> S4; S9 is a hidden copy, ignored.",
    "components": [{
      "label": "Pavele 8 cm", "measure": "area",
      "entries": ["S4"], "subtract_entries": [],
      "sources": [], "subtract_sources": [],
      "region": "site", "tolerance_m": null,
      "factors": [{"name": "grosime", "value": 0.08, "unit": "m", "origin": "assumed", "note": "…"}]
    }],
    "assumptions": ["…"], "questions": ["…"]
  }],
  "general_notes": ["…"], "questions_for_user": ["…"]
}
```

- `measure`: `area`, `length`, `perimeter`, `count`, `strip_area`, `enclosed_area`,
  `count_groups` ([engine.md](engine.md)).
- `entries` / `subtract_entries`: catalogue ids. `sources` / `subtract_sources`: raw filters
  (`layer`, `kinds`, `pattern`, `color`, `block`, `table_object`, `handles`) — an escape hatch when
  no entry fits.
- `factors` multiply the measured value; their units must make the item's unit (m² × m = m³;
  perimeter m × height m = m² of formwork). `origin` is `drawing` (written on the drawing),
  `document` (from project information, cited in the note) or `assumed` (a typical value, with a
  question for the client).
- `status`: `measured`, `assumption_based`, `not_in_drawing`. The engine downgrades `measured`
  to `assumption_based` when an assumed factor is used.

## Validation and repair

`ai/validation.py:prepare_plan` expands entry ids into filters and checks every raw filter against
the drawing: the layer exists, the pattern and colour occur on it, the table object exists.
The API backends send the problems back once and ask for a corrected plan; the remaining issues are
recorded in the plan's `_meta` and shown in the review report.

## The review pass

After the first plan, the engine measures it and the model gets a plain-text **measurement
report** (`ai/review.py`): for every item and component, what each source matched (number and kind
of entities, drawn area / length, block names, symbol group sizes, hidden layers), sources that
match nothing, engine warnings, unit mismatches, and the cross-checks (the same surface or curb
counted twice). The model answers with `REVIEW_SCHEMA`: verdict `ok`, or `revised` with only the
corrected or added items and the ids to drop, and one short note per change.

- The review request repeats the first prompt word for word, so it is served from the cache:
  a confirmation costs seconds.
- A revision that names things the drawing does not have (more validation issues than the first
  plan) is rejected and the first plan kept.
- The outcome is shown in the UI (*Verificarea AI*), recorded in the Excel *Info* sheet, and the
  run folder keeps `plan_first.json`, `review_report.txt` and `review.json`.
- `DWG_TAKEOFF_REVIEW=0` or `dwg-takeoff ask --no-review` skips it.

## Progress, cancellation, errors

Backends report `PlanEvent`s — stage, done, thought (the model's own notes), lookup and its result
count, usage, warning — which the web UI shows as a timeline. A `CancelToken` stops a job (the
Codex process is killed; API streams are abandoned). Codex errors a user can act on (the
subscription's usage limit with its reset time, not logged in) are turned into plain messages.
Timeouts: `DWG_TAKEOFF_TIMEOUT` (Codex, 900 s); the API clients use 900 s with two retries.

## What is sent to the provider

The digest (layer names, legend labels, texts, table contents, quantities), the project
information you added, and the request — not the drawing file. The Codex backend can read
`features.csv` (every entity inside the site region: layer, kind, size, position, text) in its
sandbox. Nothing is sent until you ask a question.

## Choosing effort and models

*normală* (medium) is the default. In our tests high effort gave the same quantities with 30–60 %
more time; low effort matched on simple drawings; a smaller model was four times faster but made
unit errors (paving in m³) and missed elements. Quality first: keep the defaults unless you have
measured otherwise on your drawings ([evaluation.md](evaluation.md)).
