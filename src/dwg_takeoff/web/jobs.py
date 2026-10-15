"""Analysis jobs: a question runs in a background thread (AI plan, review, measurement) while the
UI polls its progress events. Finished jobs stay in memory for an hour; the run folder keeps
everything for good."""

from __future__ import annotations

import json
import re
import threading
import time
import traceback
import uuid

from .. import config
from ..ai.planner import make_plan
from ..ai.request import Cancelled, CancelToken, PlannerError
from ..engine.executor import execute_plan
from ..project_info import ProjectInfo
from ..store import STORE, Project

JOBS: dict[str, dict] = {}
KEEP_FINISHED_S = 3600


def typical_seconds(backend: str, effort: str) -> float | None:
    """Median AI time of previous runs with the same backend and effort (any drawing), shown as
    the expected duration."""
    times = []
    for run_dir in sorted(config.CACHE_DIR.glob("*/runs/*"), key=lambda d: d.name, reverse=True)[:80]:
        meta = {}
        for name in ("plan.json", "result.json"):  # older runs kept the timing only in result.json
            try:
                data = json.loads((run_dir / name).read_text())
            except (OSError, ValueError):
                continue
            meta = (data.get("plan") or {}).get("_meta") if name == "result.json" else data.get("_meta")
            if meta:
                break
        meta = dict(meta or {})
        if "effort" not in meta:  # older runs: the effort is only in Codex's own log header
            try:
                m = re.search(r"reasoning effort:\s*(\w+)", (run_dir / "codex.log").read_text()[:4000])
                meta["effort"] = m.group(1) if m else "medium"
            except OSError:
                pass
        if meta.get("edited") or not meta.get("seconds"):
            continue
        if meta.get("backend", "codex") == backend and meta.get("effort", "medium") == effort:
            times.append(float(meta["seconds"]))
    if not times:
        return None
    times.sort()
    return round(times[len(times) // 2], 1)


def _emit(job: dict, kind: str, text: str, **kw) -> None:
    ev = {"kind": kind, "text": text, "t": round(time.time() - job["started"], 1)}
    ev.update({k: v for k, v in kw.items() if v is not None})
    job["events"].append(ev)
    if kind == "stage":
        job["stage"] = text


def _project_info_event(job: dict, pi: ProjectInfo) -> None:
    notes, n_docs = pi.notes().strip(), len(pi.documents())
    detail = (
        ("note" if notes else "")
        + (" + " if notes and n_docs else "")
        + (f"{n_docs} documente de referință" if n_docs else "")
    )
    _emit(job, "done", "Informații de proiect incluse", detail=detail)


def _run(job: dict, p: Project, query: str, model: str | None) -> None:
    cancel: CancelToken = job["_cancel"]
    try:
        _emit(job, "stage", "Pregătesc desenul")
        STORE.load(p)
        _emit(
            job,
            "done",
            "Desen pregătit",
            detail=f"{len(p.drawing.features):,} entități, "
            f"{len(p.drawing.legends)} legende, {len(p.drawing.tables)} tabele".replace(",", " "),
        )
        run_dir = p.new_run_dir()
        job["run"] = run_dir.name
        pi = ProjectInfo(p.cache_dir)
        info_text = pi.prompt_text()
        if info_text:
            _project_info_event(job, pi)

        def on_event(e):
            _emit(job, e.kind, e.text, id=e.id, detail=e.detail)

        plan = make_plan(
            query,
            p.drawing,
            p.digest,
            p.digest_text,
            p.focus["polygon"] if p.focus else None,
            run_dir,
            model=model,
            effort=job["effort"],
            on_event=on_event,
            backend=job["backend"],
            table_transform=p.table_transform,
            cancel=cancel,
            project_info=info_text,
            regions=p.regions,
            labels=p.labels(),
        )
        _emit(job, "stage", "Calculez cantitățile din geometrie")
        t = time.time()
        res = execute_plan(plan, p.drawing, p.regions, p.table_transform)
        res.update(plan=plan, query=query, run=run_dir.name)
        (run_dir / "result.json").write_text(json.dumps(res, ensure_ascii=False, default=str))
        _emit(job, "done", "Cantități calculate", detail=f"{time.time() - t:.1f} s")
        job["result"] = res
        job["status"] = "done"
    except Cancelled as e:
        job["status"] = "cancelled"
        job["error"] = str(e)
    except PlannerError as e:
        job["status"] = "error"
        job["error"] = str(e)
    except Exception as e:  # anything else: shown to the user, traced in the server log
        traceback.print_exc()
        job["status"] = "error"
        job["error"] = f"{type(e).__name__}: {e}"
    job["finished"] = time.time()


def start(p: Project, query: str, backend: dict, effort: str, model: str | None) -> str:
    """Start an analysis in the background; returns the job id."""
    jid = uuid.uuid4().hex[:12]
    job = {
        "id": jid,
        "project": p.id,
        "status": "running",
        "stage": "Pornire",
        "started": time.time(),
        "query": query,
        "backend": backend["name"],
        "backend_label": backend["label"],
        "effort": effort,
        "typical_seconds": typical_seconds(backend["name"], effort),
        "events": [],
        "_cancel": CancelToken(),
    }
    for old in [k for k, j in JOBS.items() if j.get("finished") and time.time() - j["finished"] > KEEP_FINISHED_S]:
        JOBS.pop(old, None)
    JOBS[jid] = job
    threading.Thread(target=_run, args=(job, p, query, model), daemon=True).start()
    return jid


def public(job: dict) -> dict:
    """The job as the UI sees it."""
    end = job.get("finished") or time.time()
    return {k: v for k, v in job.items() if k not in ("started", "_cancel")} | {
        "elapsed": round(end - job["started"], 1)
    }
