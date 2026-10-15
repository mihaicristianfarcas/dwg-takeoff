"""Codex CLI backend: uses the user's ChatGPT/Codex subscription through `codex exec`.

Codex runs as a read-only agent in the run directory (it can grep `features.csv` / `digest.json`)
and must answer with JSON matching the plan schema. Its `--json` event stream is turned into
progress events (what it says it is doing, each lookup command it runs).

Tuning: the user's own Codex config (plugins, MCP servers, notifications) is skipped with
`--ignore-user-config` - only the model named there is kept - and the list of installed skills
is left out (the catalogue guide is part of the prompt), which trims every request.
Set DWG_TAKEOFF_CODEX_USER_CONFIG=1 to load the full user config instead.
"""

from __future__ import annotations

import csv
import json
import re
import shutil
import subprocess
import threading
import time
import tomllib
from pathlib import Path

from shapely.prepared import prep

from .. import config
from ..analysis.catalogue import write_csv
from ..cad.model import Drawing
from .prompt import LOOKUP_FILES, instructions
from .request import Cancelled, PlannerError, PlanRequest
from .review import REVIEW_SCHEMA, review_text
from .schema import PLAN_SCHEMA


def _bin() -> str | None:
    return shutil.which("codex")


def user_model() -> str | None:
    """The model configured in the user's Codex config (kept when the config itself is skipped)."""
    if config.codex_model():
        return config.codex_model()
    try:
        return tomllib.loads((config.codex_home() / "config.toml").read_text()).get("model")
    except (OSError, tomllib.TOMLDecodeError):
        return None


_STATUS_CACHE: dict = {}


def status() -> tuple[bool, str]:
    exe = _bin()
    if not exe:
        return False, "Codex CLI nu este instalat (npm i -g @openai/codex) — apoi `codex login`."
    if "login" not in _STATUS_CACHE or time.time() - _STATUS_CACHE["t"] > 300:
        try:
            p = subprocess.run([exe, "login", "status"], capture_output=True, text=True, timeout=20)
            ok = p.returncode == 0 and "not logged" not in (p.stdout + p.stderr).lower()
            _STATUS_CACHE.update(login=(ok, (p.stdout or p.stderr).strip()), t=time.time())
        except Exception as e:
            _STATUS_CACHE.update(login=(False, str(e)), t=time.time())
    ok, msg = _STATUS_CACHE["login"]
    return (
        (True, msg or "Codex conectat") if ok else (False, f"Codex nu este autentificat: rulați `codex login` ({msg})")
    )


_FRIENDLY = [
    (re.compile(r"catalogue\.csv"), "Caută în catalogul planșei"),
    (re.compile(r"\b(rg|grep)\b"), "Caută în entitățile planșei"),
    (re.compile(r"\bpython3?\b"), "Analizează datele planșei (Python)"),
    (re.compile(r"\bawk\b"), "Filtrează entitățile planșei"),
    (re.compile(r"\b(head|tail|cat|sed)\b"), "Citește datele planșei"),
    (re.compile(r"\bjq\b"), "Citește rezumatul planșei"),
    (re.compile(r"\bwc\b"), "Numără entitățile"),
]


def _clean_command(cmd: str) -> str:
    m = re.match(r"^/bin/(?:ba|z)?sh -lc (['\"])(.*)\1$", cmd.strip(), re.S)
    return (m.group(2) if m else cmd).strip()


def describe_command(cmd: str) -> str:
    c = _clean_command(cmd)
    for rx, label in _FRIENDLY:
        if rx.search(c):
            return label
    return "Verifică datele planșei"


def _prompt(req: PlanRequest) -> str:
    return (
        instructions(LOOKUP_FILES)
        + "\n\n=== DRAWING DIGEST ===\n"
        + req.digest_text
        + "\n\n"
        + req.request_text()
        + "\n"
    )


def friendly_error(text: str) -> str | None:
    """Plain-language message for the Codex failures a user can act on."""
    low = text.lower()
    if "usage limit" in low:
        m = re.search(r"try again (at|in) ([^.;]+)", text, re.I)
        when = f" Reîncercați {'după' if m.group(1).lower() == 'at' else 'peste'} {m.group(2).strip()}." if m else ""
        return (
            "Limita de utilizare a abonamentului ChatGPT/Codex a fost atinsă."
            + when
            + " Între timp puteți folosi un motor API (Claude / OpenAI) dacă are cheie configurată."
        )
    if "not logged in" in low or "unauthorized" in low or "401" in low:
        return "Codex nu este autentificat: rulați `codex login` în terminal."
    return None


def write_features_csv(drawing: Drawing, region, path: Path) -> None:
    """Every entity inside the site region, one row each: the file Codex may grep."""
    pf = prep(region) if region is not None else None
    s = drawing.unit_scale
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "fid",
                "handle",
                "layer",
                "kind",
                "dxftype",
                "pattern",
                "color",
                "block",
                "area_m2",
                "length_m",
                "width_m",
                "x",
                "y",
                "visible",
                "nested",
                "text",
            ]
        )
        for ft in drawing.features:
            if ft.nested and ft.kind == "line":
                continue  # block internals (furniture, symbols) - too noisy
            p = ft.geom.representative_point()
            if pf is not None and not pf.contains(p):
                continue
            text = ft.text or ("; ".join(f"{k}={v}" for k, v in ft.attribs.items()) if ft.attribs else "")
            w.writerow(
                [
                    ft.fid,
                    ft.handle,
                    ft.layer,
                    ft.kind,
                    ft.dxftype,
                    ft.pattern or "",
                    ft.color or "",
                    ft.block or "",
                    round(ft.area * s * s, 3),
                    round(ft.length * s, 3),
                    round(ft.width * s, 3) if ft.width else "",
                    round(p.x, 3),
                    round(p.y, 3),
                    int(ft.visible),
                    int(ft.nested),
                    text[:120].replace("\n", " "),
                ]
            )


def plan(req: PlanRequest) -> dict:
    run = req.run_dir
    run.mkdir(parents=True, exist_ok=True)
    (run / "digest.json").write_text(json.dumps(req.digest, ensure_ascii=False, indent=1, default=str))
    write_features_csv(req.drawing, req.region, run / "features.csv")
    if (req.digest or {}).get("catalogue"):
        write_csv(req.digest["catalogue"], req.labels, run / "catalogue.csv")
    (run / "schema.json").write_text(json.dumps(PLAN_SCHEMA, ensure_ascii=False, indent=1))
    prompt = _prompt(req)
    (run / "prompt.txt").write_text(prompt)
    return _exec(req, prompt, "schema.json", "plan.json", "codex", "AI analizează desenul și cererea")


def review(req: PlanRequest, plan: dict, report: str) -> dict:
    """Second turn: the same prompt (served from the prompt cache) + the plan + what was measured."""
    run = req.run_dir
    (run / "review_schema.json").write_text(json.dumps(REVIEW_SCHEMA, ensure_ascii=False, indent=1))
    prompt = _prompt(req) + "\n" + review_text(plan, report)
    (run / "review_prompt.txt").write_text(prompt)
    return _exec(req, prompt, "review_schema.json", "review.json", "codex-review", "AI verifică rezultatele măsurate")


def _exec(req: PlanRequest, prompt: str, schema: str, out_name: str, log_name: str, stage: str) -> dict:
    exe = _bin()
    if not exe:
        raise PlannerError("Codex CLI not found (install `codex` and log in with `codex login`).")
    run = req.run_dir
    model = req.model or user_model()
    cmd = [
        exe,
        "exec",
        "--skip-git-repo-check",
        "--ephemeral",
        "-s",
        "read-only",
        "--json",
        "--output-schema",
        schema,
        "-o",
        out_name,
        "-c",
        f'model_reasoning_effort="{req.effort}"',
        # the catalogue guide is already in the prompt; Codex's own list of installed skills
        # (the repo's dwg-catalogue skill included) would only add tokens and a lookup round
        "-c",
        "skills.include_instructions=false",
    ]
    if not config.codex_user_config():
        cmd.append("--ignore-user-config")
    if model:
        cmd += ["-m", model]
    cmd.append("-")
    timeout = config.codex_timeout()

    req.say("stage", stage, detail=f"Codex · {model or 'model implicit'} · efort {req.effort}")
    t0 = time.time()
    (run / out_name).unlink(missing_ok=True)
    proc = subprocess.Popen(
        cmd, cwd=run, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1
    )
    req.cancel.on_cancel.append(proc.kill)
    killed_by_timeout = threading.Event()

    def watchdog():
        if proc.poll() is None:
            killed_by_timeout.set()
            proc.kill()

    timer = threading.Timer(timeout, watchdog)
    timer.start()
    stderr_buf: list[str] = []
    err_thread = threading.Thread(target=lambda: stderr_buf.extend(proc.stderr), daemon=True)
    err_thread.start()
    proc.stdin.write(prompt)
    proc.stdin.close()

    usage = None
    errors: list[str] = []
    lookups = 0
    with open(run / f"{log_name}.jsonl", "w") as log:
        for line in proc.stdout:
            log.write(line)
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            et = ev.get("type", "")
            item = ev.get("item") or {}
            it = item.get("type")
            if et == "item.started" and it == "command_execution":
                lookups += 1
                c = _clean_command(item.get("command", ""))
                req.say("lookup", describe_command(c), id=item.get("id"), detail=c[:300])
            elif et == "item.completed" and it == "command_execution":
                out = item.get("aggregated_output") or ""
                n = len(out.splitlines())
                ok = item.get("exit_code") == 0
                req.say("lookup_done", f"{n} rânduri găsite" if ok else "comanda a eșuat", id=item.get("id"))
            elif et == "item.completed" and it == "agent_message":
                text = (item.get("text") or "").strip()
                if text and not text.startswith("{"):
                    req.say("thought", text[:400])
            elif et == "item.completed" and it == "reasoning":
                text = (item.get("text") or "").strip()
                if text:
                    req.say("thought", text[:400])
            elif et == "turn.completed":
                usage = ev.get("usage")
            elif et in ("error", "turn.failed"):
                msg = ev.get("message") or (ev.get("error") or {}).get("message") or json.dumps(ev)[:300]
                errors.append(msg)
    proc.wait()
    timer.cancel()
    err_thread.join(timeout=2)
    (run / f"{log_name}.log").write_text("".join(stderr_buf))
    elapsed = time.time() - t0
    if req.cancel.cancelled:
        raise Cancelled("Analiza a fost anulată.")
    if killed_by_timeout.is_set():
        raise PlannerError(f"Codex nu a răspuns în {timeout} s.")
    out = run / out_name
    if proc.returncode != 0 or not out.exists():
        tail = ("; ".join(dict.fromkeys(errors)) or "".join(stderr_buf)[-1500:]).strip()
        raise PlannerError(
            friendly_error(tail) or f"codex exec failed (exit {proc.returncode}) after {elapsed:.0f}s: {tail}"
        )
    try:
        result = json.loads(out.read_text())
    except json.JSONDecodeError as e:
        raise PlannerError(f"Codex returned invalid JSON: {e}") from e
    if usage:
        req.say(
            "usage",
            f"{usage.get('input_tokens', 0):,} tokeni intrare ({usage.get('cached_input_tokens', 0):,} din cache), "
            f"{usage.get('output_tokens', 0):,} ieșire".replace(",", " "),
        )
    result["_meta"] = {
        "backend": "codex",
        "model": model or "codex default",
        "effort": req.effort,
        "seconds": round(elapsed, 1),
        "lookups": lookups,
        "usage": usage,
    }
    return result
