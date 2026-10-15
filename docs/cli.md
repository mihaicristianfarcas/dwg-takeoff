# Command line

```
dwg-takeoff [--version] COMMAND …
```

Run it with `uv run dwg-takeoff …` from a checkout (or `python -m dwg_takeoff`). Every command
loads the drawing through the same cache as the web app (`DWG_TAKEOFF_DATA`), so a drawing opened
once is instant afterwards, from either side.

## serve

```bash
dwg-takeoff serve [--host 127.0.0.1] [--port 8765]
```

Starts the web app. Drawings in `samples/` (or `DWG_TAKEOFF_SAMPLES`) and earlier uploads are
loaded in the background. Keep the default host: the server has no authentication
([../SECURITY.md](../SECURITY.md)).

## inspect

```bash
dwg-takeoff inspect FILE [FILE …]
```

A health check per drawing: DWG version, units with their confidence and evidence, the measured
space, entity counts by kind, layers, legend entries, tables, the site region, georeferenced
setting-out tables, warnings (unbound xrefs, drawings made on a sheet) and the timings of each
stage. Use it on a new drawing before asking anything.

## digest

```bash
dwg-takeoff digest FILE
```

Prints the drawing part of the AI prompt, exactly as the model reads it (with the user's labels).

## catalogue

```bash
dwg-takeoff catalogue FILE                 # the 300 most relevant entries, as in the prompt
dwg-takeoff catalogue FILE --all           # every entry
dwg-takeoff catalogue FILE --search curb   # entries whose id, label, layer, block, legend, callout or text match
dwg-takeoff catalogue FILE --entry S8      # one entry with its filters and evidence (JSON)
dwg-takeoff catalogue FILE --csv out.csv   # the whole catalogue as CSV
```

See [catalogue.md](catalogue.md) for the format.

## ask

```bash
dwg-takeoff ask FILE "REQUEST" [--backend codex|anthropic|openai] [--model M] [--effort low|medium|high]
                               [--info "slab 18 cm"] [--no-review] [--json result.json]
dwg-takeoff ask FILE "REQUEST" --plan plan.json [--json result.json]
```

Asks the AI for a plan (progress on stderr), measures it and prints every item: value, status and
confidence, formula, each component with the number of entities and the drawn vs counted sum,
warnings, assumptions, reasoning, the cross-checks and the review's outcome. The run is saved like
the web app's (it appears in *Istoric*). `--info` adds project information for this run on top of
the drawing's saved notes and documents.

With `--plan`, no AI is called: the plan file (any `plan.json` of a run, or one you write —
catalogue ids in `entries` are fine) is measured as is. Useful to re-check a plan, to compare
engine versions, or for agents that write plans themselves.

## install-skill

```bash
dwg-takeoff install-skill [--dir .]
```

Copies the `dwg-catalogue` skill (`src/dwg_takeoff/ai/skills/dwg-catalogue/`) to
`.claude/skills/` (Claude Code) and `.agents/skills/` (Codex) under `--dir`. Run it after editing
the skill; a test fails while the copies differ.
