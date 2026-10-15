"""Projects: drawings loaded once and kept, with their digest, in memory and on disk.

A project's folder (``<data>/cache/<file hash>/``) holds the converted DXF, the extraction cache
(a pickle, rebuilt when `PIPELINE_VERSION` changes), the rendered views, the user's labels and
units, project information, and one folder per analysis run (prompt, plan, result, logs).
"""

from __future__ import annotations

import json
import multiprocessing as mp
import os
import pickle
import threading
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import config
from .analysis.catalogue import Labels
from .analysis.digest import build_digest, digest_to_text
from .analysis.site import focus_region
from .cad import convert
from .cad.entities import load_doc
from .cad.extract import apply_units, extract
from .cad.georef import georeference_tables
from .cad.model import Drawing

# Bump whenever extraction, the digest or the catalogue change what they produce, or a pickled
# class moves: cached projects are then rebuilt from the DXF on their next load.
PIPELINE_VERSION = "27"


@dataclass
class Project:
    id: str
    name: str
    source_path: Path
    cache_dir: Path
    status: str = "pending"  # pending | converting | extracting | ready | error
    error: str | None = None
    drawing: Drawing | None = None
    digest: dict | None = None
    digest_text: str | None = None
    focus: dict | None = None
    table_transform: object | None = None
    timings: dict = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def regions(self) -> dict:
        return {"site": self.focus["polygon"]} if self.focus else {}

    @property
    def context(self) -> dict:
        return {"regions": self.regions, "table_transform": self.table_transform}

    def info(self) -> dict:
        d = {"id": self.id, "name": self.name, "status": self.status, "error": self.error, "timings": self.timings}
        if self.drawing is not None:
            d.update(
                {
                    "units": self.drawing.units,
                    "dxf_version": self.drawing.dxf_version,
                    "dwg_version": convert.dwg_version(self.source_path)
                    if self.source_path.suffix.lower() == ".dwg"
                    else None,
                    "n_features": len(self.drawing.features),
                    "n_layers": len(self.drawing.layers),
                    "unit_scale": self.drawing.unit_scale,
                    "unit_info": {
                        k: v for k, v in (self.drawing.unit_info or {}).items() if k not in ("measurement", "lunits")
                    },
                    "space": self.drawing.space,
                }
            )
        return d

    def unit_override(self) -> int | dict | None:
        """Unit code chosen by the user, or {"scale": m per unit} calibrated on a known length."""
        try:
            d = json.loads((self.cache_dir / "units.json").read_text())
        except (OSError, ValueError):
            return None
        return {"scale": float(d["scale"])} if d.get("scale") else d.get("code")

    def labels(self) -> dict:
        return Labels(self.cache_dir).all()

    def refresh_text(self) -> None:
        """The AI's view of the drawing (catalogue with the user's current labels)."""
        self.digest_text = digest_to_text(self.digest, labels=self.labels())

    def runs_dir(self) -> Path:
        d = self.cache_dir / "runs"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def new_run_dir(self) -> Path:
        return self.runs_dir() / datetime.now().strftime("%Y%m%d-%H%M%S-%f")


class Store:
    def __init__(self):
        self.projects: dict[str, Project] = {}
        self._lock = threading.Lock()
        self.use_processes = False  # the web server turns this on

    def add(self, path: str | Path, name: str | None = None) -> Project:
        path = Path(path)
        pid = convert.file_hash(path)
        with self._lock:
            if pid in self.projects:
                return self.projects[pid]
            cache = config.CACHE_DIR / pid
            cache.mkdir(parents=True, exist_ok=True)
            p = Project(pid, name or path.name, path, cache)
            self.projects[pid] = p
            return p

    def get(self, pid: str) -> Project | None:
        return self.projects.get(pid)

    def load(self, p: Project) -> Project:
        """Convert + extract + digest (cached). Safe to call repeatedly / concurrently."""
        with p.lock:
            if p.status == "ready":
                return p
            try:
                pkl = p.cache_dir / f"drawing-v{PIPELINE_VERSION}.pkl"
                for old in p.cache_dir.glob("drawing-v*.pkl"):
                    if old != pkl:
                        old.unlink(missing_ok=True)  # outdated extraction format
                if not pkl.exists() and self.use_processes:
                    # heavy, GIL-bound work in a worker process: the web server stays responsive
                    p.status = "converting"
                    p.timings.update(
                        worker_pool()
                        .submit(build_cache, str(p.source_path), p.name, str(p.cache_dir), str(pkl), p.unit_override())
                        .result()
                    )
                if pkl.exists():
                    p.status = "extracting"
                    t = time.time()
                    with open(pkl, "rb") as f:
                        p.drawing, p.digest, p.table_transform = pickle.load(f)
                    p.timings["load_cache_s"] = round(time.time() - t, 1)
                else:
                    p.status = "converting"
                    t = time.time()
                    dxf = convert.to_dxf(p.source_path)
                    p.timings["convert_s"] = round(time.time() - t, 1)
                    p.status = "extracting"
                    t = time.time()
                    doc = load_doc(dxf)
                    p.drawing = extract(dxf, p.name, doc, unit_override=p.unit_override())
                    p.timings["extract_s"] = round(time.time() - t, 1)
                    self._analyse(p, pkl)
                p.focus = focus_region(p.drawing)
                p.refresh_text()
                p.status = "ready"
                p.error = None
            except Exception as e:  # surfaced to the UI
                p.status = "error"
                p.error = f"{type(e).__name__}: {e}"
                raise
        return p

    def _analyse(self, p: Project, pkl: Path) -> None:
        """Site region, georeferencing and digest (everything that depends on the unit scale)."""
        t = time.time()
        focus = focus_region(p.drawing)
        try:
            p.table_transform = georeference_tables(p.drawing, focus["polygon"] if focus else None)
        except Exception:
            p.table_transform = None
        p.digest = build_digest(p.drawing, p.table_transform)
        p.timings["digest_s"] = round(time.time() - t, 1)
        tmp = pkl.with_name(f"{pkl.name}.{os.getpid()}.tmp")  # atomic: readers never see half a file
        with open(tmp, "wb") as f:
            pickle.dump((p.drawing, p.digest, p.table_transform), f)
        os.replace(tmp, pkl)

    def set_units(self, p: Project, code: int | None, scale: float | None = None) -> Project:
        """Override the drawing units with a unit code or a calibrated scale (m per drawing unit),
        or reset with neither; quantities, site region and digest are recomputed from the cached
        geometry."""
        self.load(p)
        with p.lock:
            f = p.cache_dir / "units.json"
            override = {"scale": scale} if scale else code
            if override:
                f.write_text(json.dumps({"scale": scale} if scale else {"code": code}))
            else:
                f.unlink(missing_ok=True)
            apply_units(p.drawing, override)
            self._analyse(p, p.cache_dir / f"drawing-v{PIPELINE_VERSION}.pkl")
            p.focus = focus_region(p.drawing)
            p.refresh_text()
        return p


STORE = Store()

_POOL = None


def worker_pool():
    """Process pool for extraction and rendering (both are CPU-bound pure Python)."""
    global _POOL
    if _POOL is None:
        _POOL = ProcessPoolExecutor(max_workers=config.worker_count(), mp_context=mp.get_context("spawn"))
    return _POOL


def build_cache(source_path: str, name: str, cache_dir: str, pkl: str, unit_override: int | dict | None) -> dict:
    """Worker-process job: convert, extract and analyse a drawing, write its cache pickle and
    return the stage timings."""
    p = Project("", name, Path(source_path), Path(cache_dir))
    t = time.time()
    dxf = convert.to_dxf(p.source_path)
    p.timings["convert_s"] = round(time.time() - t, 1)
    t = time.time()
    p.drawing = extract(dxf, name, load_doc(dxf), unit_override=unit_override)
    p.timings["extract_s"] = round(time.time() - t, 1)
    Store()._analyse(p, Path(pkl))
    return p.timings
