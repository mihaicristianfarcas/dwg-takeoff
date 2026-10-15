"""Lookups shared by the routes, with the HTTP errors they raise."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import HTTPException

from ..store import STORE, Project

RUN_NAME = re.compile(r"\d{8}-\d{6}-\d{6}")


def get_project(pid: str, ready: bool = True) -> Project:
    """The project, or 404; with `ready`, 409 while it is still being processed (500 if that failed)."""
    p = STORE.get(pid)
    if p is None:
        raise HTTPException(404, "Unknown drawing")
    if ready and p.status != "ready":
        if p.status == "error":
            raise HTTPException(500, p.error or "processing failed")
        raise HTTPException(409, f"Drawing is still being processed ({p.status})")
    return p


def run_dir(p: Project, run: str) -> Path:
    """A run folder of the project; the name is validated (no path tricks, no deleted runs)."""
    if not RUN_NAME.fullmatch(run):
        raise HTTPException(404)
    return p.runs_dir() / run
