"""Settings. Everything is configured with environment variables; this module is the one place
that lists them (see docs/configuration.md).

Paths are resolved when the package is imported; the other settings are read when they are used,
so a test or a long-running server sees the current environment.
"""

from __future__ import annotations

import os
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
SOURCE_ROOT = PACKAGE_DIR.parents[1]  # the repository, when running from a checkout


def _default_data_dir() -> Path:
    if (SOURCE_ROOT / "pyproject.toml").exists():
        return SOURCE_ROOT / "data"
    return Path.cwd() / "dwg-takeoff-data"


# where converted drawings, caches, runs and labels are kept
DATA_DIR = Path(os.environ.get("DWG_TAKEOFF_DATA") or _default_data_dir())
CACHE_DIR = DATA_DIR / "cache"
UPLOADS_DIR = DATA_DIR / "uploads"
# drawings loaded when the web server starts
SAMPLES_DIR = Path(os.environ.get("DWG_TAKEOFF_SAMPLES") or SOURCE_ROOT / "samples")


def env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def env_int(name: str, default: int) -> int:
    try:
        return int(env(name, str(default)))
    except ValueError:
        return default


def env_flag(name: str, default: bool) -> bool:
    value = env(name)
    return default if value is None else value not in ("0", "false", "no", "off")


# --- drawing conversion --------------------------------------------------------------------


def oda_executable() -> str | None:
    """DWG_TAKEOFF_ODA: path of the ODA File Converter executable (searched for when unset)."""
    return env("DWG_TAKEOFF_ODA")


def convert_timeout() -> int:
    """DWG_TAKEOFF_CONVERT_TIMEOUT: seconds one DWG -> DXF conversion may take (600)."""
    return env_int("DWG_TAKEOFF_CONVERT_TIMEOUT", 600)


# --- processing ----------------------------------------------------------------------------


def worker_count() -> int:
    """DWG_TAKEOFF_WORKERS: processes for extraction and rendering (half the CPUs, at most 3)."""
    return env_int("DWG_TAKEOFF_WORKERS", max(1, min(3, (os.cpu_count() or 2) // 2)))


def in_process() -> bool:
    """DWG_TAKEOFF_INPROCESS=1: the web server does all work in its own process (tests)."""
    return env_flag("DWG_TAKEOFF_INPROCESS", False)


# --- AI ------------------------------------------------------------------------------------


def default_backend() -> str:
    """DWG_TAKEOFF_AI: codex (default) | anthropic | openai."""
    return env("DWG_TAKEOFF_AI", "codex")


def review_enabled() -> bool:
    """DWG_TAKEOFF_REVIEW=0 skips the AI check of the measured plan."""
    return env_flag("DWG_TAKEOFF_REVIEW", True)


def codex_home() -> Path:
    """CODEX_HOME: the Codex CLI's configuration folder (~/.codex)."""
    return Path(env("CODEX_HOME") or Path.home() / ".codex")


def codex_model() -> str | None:
    """DWG_TAKEOFF_CODEX_MODEL (or DWG_TAKEOFF_MODEL): model for Codex; default: Codex's own."""
    return env("DWG_TAKEOFF_CODEX_MODEL") or env("DWG_TAKEOFF_MODEL")


def codex_user_config() -> bool:
    """DWG_TAKEOFF_CODEX_USER_CONFIG=1 loads the full Codex user config (plugins, MCP servers)."""
    return env_flag("DWG_TAKEOFF_CODEX_USER_CONFIG", False)


def codex_timeout() -> int:
    """DWG_TAKEOFF_TIMEOUT: seconds one Codex request may take (900)."""
    return env_int("DWG_TAKEOFF_TIMEOUT", 900)


def anthropic_model() -> str:
    """DWG_TAKEOFF_ANTHROPIC_MODEL: Claude model of the Anthropic API backend."""
    return env("DWG_TAKEOFF_ANTHROPIC_MODEL", "claude-opus-5-5")


def openai_model() -> str | None:
    """DWG_TAKEOFF_OPENAI_MODEL: model of the OpenAI API backend (default: the Codex model)."""
    return env("DWG_TAKEOFF_OPENAI_MODEL")
