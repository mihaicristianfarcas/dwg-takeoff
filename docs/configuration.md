# Configuration

Everything is configured with environment variables, all read in one place:
[`src/dwg_takeoff/config.py`](../src/dwg_takeoff/config.py). Unset or empty means the default.

## Files

| Variable | Default | |
|---|---|---|
| `DWG_TAKEOFF_DATA` | `data/` in the checkout | converted drawings, caches, runs, labels, uploads ([architecture.md](architecture.md#projects-caching-and-the-data-folder)) |
| `DWG_TAKEOFF_SAMPLES` | `samples/` in the checkout | drawings loaded when the server starts |

## Drawing conversion

| Variable | Default | |
|---|---|---|
| `DWG_TAKEOFF_ODA` | searched for | path of the ODA File Converter executable |
| `DWG_TAKEOFF_CONVERT_TIMEOUT` | `600` | seconds one DWG → DXF conversion may take |

## Processing

| Variable | Default | |
|---|---|---|
| `DWG_TAKEOFF_WORKERS` | half the CPUs, at most 3 | worker processes for extraction and rendering |
| `DWG_TAKEOFF_INPROCESS` | off | `1`: the server does everything in its own process (tests, debugging) |

## AI

| Variable | Default | |
|---|---|---|
| `DWG_TAKEOFF_AI` | `codex` | default backend: `codex`, `anthropic` or `openai` (the UI can pick per request) |
| `DWG_TAKEOFF_REVIEW` | on | `0`: skip the AI's check of the measured plan |
| `DWG_TAKEOFF_CODEX_MODEL` (or `DWG_TAKEOFF_MODEL`) | the model in `~/.codex/config.toml` | model for the Codex backend |
| `DWG_TAKEOFF_CODEX_USER_CONFIG` | off | `1`: load your full Codex configuration (plugins, MCP servers) instead of the lean one |
| `DWG_TAKEOFF_TIMEOUT` | `900` | seconds one Codex request may take |
| `CODEX_HOME` | `~/.codex` | the Codex CLI's configuration folder |
| `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` | — | Claude API credentials (an `ant auth login` profile also works) |
| `DWG_TAKEOFF_ANTHROPIC_MODEL` | `claude-opus-5-5` | Claude model |
| `OPENAI_API_KEY` | — | OpenAI API key |
| `DWG_TAKEOFF_OPENAI_MODEL` | the Codex model | OpenAI model |

## Tests

| Variable | |
|---|---|
| `DWG_TAKEOFF_UI_TESTS=1` | run the browser tests (`tests/test_ui.py`; needs `uv run playwright install`) |
