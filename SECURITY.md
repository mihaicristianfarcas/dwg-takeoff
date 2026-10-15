# Security

## Supported versions

The latest release on `main`.

## Reporting a vulnerability

Report it privately through GitHub's *Security → Report a vulnerability* on this repository
(private vulnerability reporting). Please include what an attacker could do and how to reproduce
it.

## Deployment model

DWG Takeoff is a **local, single-user tool**:

- The server binds to `127.0.0.1` by default and has **no authentication**. Do not expose it to a
  network (`--host 0.0.0.0`) or the internet; anyone who can reach it can upload files, read every
  loaded drawing and start AI requests on your account. Put it behind an authenticating proxy if
  you must share it.
- State-changing requests from other web sites open in the same browser are refused (`Origin`
  check); file names of runs and documents are validated against path traversal.
- Uploaded drawings are parsed by ezdxf after conversion by the ODA File Converter (a separate,
  closed-source program); treat drawings from untrusted sources like any other untrusted file.

## Data sent to AI providers

When you ask a question, the chosen backend sends the **digest** of the drawing — layer names,
legend labels, texts, table contents, measured quantities — plus your project notes, reference
document texts and the request, to the provider (OpenAI through the Codex CLI or the API, or
Anthropic). The drawing file itself is not sent; the Codex backend can read a CSV of the entities
inside the site region in its sandbox. Check that this is acceptable for the drawings you work on.
Nothing is sent until you ask a question; extraction, the catalogue, measurements and exports are
local.

## Credentials

API keys are read from the environment (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`) and never written to
the data folder or the run logs. The Codex backend uses the Codex CLI's own login.
