"""AI planning. Every backend turns (request + drawing digest) into the same JSON takeoff plan;
the deterministic engine then measures it (`planner.make_plan` is the entry point).

    codex      Codex CLI with the user's ChatGPT/Codex subscription (default)
    anthropic  Claude API (ANTHROPIC_API_KEY, pay per use)
    openai     OpenAI API (OPENAI_API_KEY, pay per use)

Choose the default with DWG_TAKEOFF_AI; the UI can pick any available backend per request.
"""

from __future__ import annotations

from .. import config
from . import anthropic_api, codex_cli, openai_api
from .request import PlannerError, PlanRequest

BACKENDS = {
    "codex": ("Codex (abonament ChatGPT)", codex_cli),
    "anthropic": ("Claude API (Anthropic)", anthropic_api),
    "openai": ("OpenAI API", openai_api),
}


def default_backend() -> str:
    name = config.default_backend()
    return name if name in BACKENDS else "codex"


def backends_status() -> list[dict]:
    """Every backend with whether it can be used now and why not."""
    out = []
    for name, (label, mod) in BACKENDS.items():
        ok, msg = mod.status()
        out.append({"name": name, "label": label, "available": ok, "detail": msg, "default": name == default_backend()})
    return out


def _backend(name: str):
    if name not in BACKENDS:
        raise PlannerError(f"Unknown AI backend '{name}'.")
    return BACKENDS[name][1]


def run_backend(name: str, req: PlanRequest) -> dict:
    return _backend(name).plan(req)


def run_review(name: str, req: PlanRequest, plan: dict, report: str) -> dict:
    return _backend(name).review(req, plan, report)
