"""DWG -> DXF conversion with the ODA File Converter (Open Design Alliance).

The converter is a free, notarized desktop app with a command-line mode:
    ODAFileConverter <in_dir> <out_dir> <version> <type> <recurse> <audit> [filter]
It converts every matching file of `in_dir`, so each drawing is copied into its own folder.
Converted files are cached under ``<data>/cache/<sha256-prefix>/``.

Install: https://www.opendesign.com/guestfiles/oda_file_converter (macOS: copy the app to
/Applications; Linux: .deb/.rpm/AppImage). Set DWG_TAKEOFF_ODA to use a custom location.
"""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import subprocess
import threading
from pathlib import Path

from .. import config

CONVERTER = "ODA File Converter"
DXF_NAME = "drawing-oda.dxf"
INSTALL_HINT = (
    "Install the ODA File Converter (free): https://www.opendesign.com/guestfiles/oda_file_converter "
    "— on macOS copy ODAFileConverter.app to /Applications; or set DWG_TAKEOFF_ODA to the executable."
)

_LOCK = threading.Lock()  # the converter is a GUI-toolkit app: run one conversion at a time


class ConversionError(RuntimeError):
    pass


class _process_lock:
    """One converter run at a time across worker processes too (file lock)."""

    def __enter__(self):
        try:
            import fcntl
        except ImportError:  # Windows: the in-process lock only
            self.f = None
            return self
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.f = open(config.DATA_DIR / ".oda.lock", "w")
        fcntl.flock(self.f, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        if self.f is not None:
            import fcntl

            fcntl.flock(self.f, fcntl.LOCK_UN)
            self.f.close()


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def cache_dir_for(path: Path) -> Path:
    d = config.CACHE_DIR / file_hash(path)
    d.mkdir(parents=True, exist_ok=True)
    return d


def dwg_version(path: Path) -> str:
    with open(path, "rb") as f:
        magic = f.read(6).decode("ascii", "replace")
    return {
        "AC1009": "AutoCAD R11/R12",
        "AC1012": "AutoCAD R13",
        "AC1014": "AutoCAD R14",
        "AC1015": "AutoCAD 2000",
        "AC1018": "AutoCAD 2004",
        "AC1021": "AutoCAD 2007",
        "AC1024": "AutoCAD 2010",
        "AC1027": "AutoCAD 2013",
        "AC1032": "AutoCAD 2018",
    }.get(magic, magic)


def sniff(path: Path) -> str:
    """ "dwg", "dxf", or why the file is neither (a failed download saved as .dwg is common)."""
    with open(path, "rb") as f:
        head = f.read(512)
    if head[:3] in (b"AC1", b"AC2"):
        return "dwg"
    text = head.decode("latin-1").lstrip().upper()
    if (text.startswith("0") and "SECTION" in text[:40]) or head.startswith(b"AutoCAD Binary DXF"):
        return "dxf"
    if text.startswith("<"):
        return "Fișierul nu este un desen DWG: conține o pagină web (descărcarea a eșuat?)."
    if not head:
        return "Fișierul este gol."
    return "Fișierul nu este un desen DWG valid (semnătura AutoCAD lipsește)."


def find_oda() -> str | None:
    import glob

    windows = sorted(glob.glob(r"C:\Program Files\ODA\ODAFileConverter*\ODAFileConverter.exe"), reverse=True)
    candidates = [
        config.oda_executable(),
        *windows,
        "/Applications/ODAFileConverter.app/Contents/MacOS/ODAFileConverter",
        str(Path.home() / "Applications/ODAFileConverter.app/Contents/MacOS/ODAFileConverter"),
        shutil.which("ODAFileConverter"),
        "/usr/bin/ODAFileConverter",
    ]
    for cand in candidates:
        if cand and Path(cand).is_file() and os.access(cand, os.X_OK):
            return cand
    return None


def converter_available() -> bool:
    return find_oda() is not None


def oda_command(exe: str, in_dir: Path, out_dir: Path) -> list[str]:
    # always pass the full argument list: without it the converter opens its GUI
    return [exe, str(in_dir), str(out_dir), "ACAD2018", "DXF", "0", "1", "*.DWG"]


def to_dxf(path: str | Path) -> Path:
    """Return a DXF path for ``path`` (converting DWG input when needed)."""
    path = Path(path)
    if path.suffix.lower() == ".dxf":
        return path
    if path.suffix.lower() != ".dwg":
        raise ConversionError(f"Unsupported file type: {path.suffix}")
    kind = sniff(path)
    if kind == "dxf":
        return path  # a DXF saved with a .dwg name
    if kind != "dwg":
        raise ConversionError(kind)

    cache = cache_dir_for(path)
    out = cache / DXF_NAME
    if out.exists() and out.stat().st_size > 0:
        return out
    exe = find_oda()
    if not exe:
        raise ConversionError(f"{CONVERTER} not found. {INSTALL_HINT}")

    work_in, work_out = cache / "oda_in", cache / "oda_out"
    with _LOCK, _process_lock():
        for d in (work_in, work_out):
            shutil.rmtree(d, ignore_errors=True)
            d.mkdir(parents=True)
        shutil.copy(path, work_in / "drawing.dwg")
        env = dict(os.environ)
        if platform.system() == "Linux":
            env.setdefault("QT_QPA_PLATFORM", "offscreen")  # headless servers
        try:
            proc = subprocess.run(
                oda_command(exe, work_in, work_out),
                capture_output=True,
                text=True,
                timeout=config.convert_timeout(),
                env=env,
            )
        except subprocess.TimeoutExpired:
            raise ConversionError(f"{CONVERTER} timed out") from None
        produced = work_out / "drawing.dxf"
        if not produced.exists() or produced.stat().st_size == 0:
            details = " ".join(p.read_text(errors="replace")[-1500:] for p in work_out.glob("*.err"))
            raise ConversionError(
                f"{CONVERTER} produced no DXF (exit {proc.returncode}). {details or proc.stderr[-1500:]}".strip()
            )
        produced.replace(out)
        shutil.rmtree(work_in, ignore_errors=True)
        shutil.rmtree(work_out, ignore_errors=True)
    # outputs of the previous converter (LibreDWG) are obsolete
    (cache / "drawing.dxf").unlink(missing_ok=True)
    return out
