"""Project information that is not in the measured drawing: the client's answers and specifications
typed by the user, and reference documents (road-structure details, foundation plans, technical
notes as PDF / DWG / DXF / text). The AI reads them to state thicknesses, depths and sections;
nothing is measured on them.
"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

from pypdf import PdfReader

from .cad.convert import to_dxf
from .cad.entities import layout_texts, load_doc
from .cad.extract import extract

MAX_CHARS = 12000  # per document, in the prompt
KINDS = {".pdf": "pdf", ".dwg": "dwg", ".dxf": "dxf", ".txt": "text", ".md": "text"}


def extract_text(path: Path) -> str:
    """Readable text of a reference document."""
    kind = KINDS.get(path.suffix.lower())
    if kind == "pdf":
        pages = []
        for i, page in enumerate(PdfReader(str(path)).pages, 1):
            t = (page.extract_text() or "").strip()
            if t:
                pages.append(f"[pagina {i}]\n{t}")
        return _clean("\n\n".join(pages))
    if kind == "text":
        return _clean(path.read_text(errors="replace"))
    if kind in ("dwg", "dxf"):
        return _clean(_drawing_text(path))
    raise ValueError(f"Tip de document nesuportat: {path.suffix}")


def _drawing_text(path: Path) -> str:
    """Texts, tables and legend labels of a drawing (sections, details: the layer geometry of a
    detail sheet carries no takeoff quantity for the site plan)."""
    dxf = to_dxf(path)
    doc = load_doc(dxf)
    d = extract(dxf, path.name, doc)
    out = []
    for name in ["Model"] + [n for n in doc.layouts.names() if n != "Model"]:
        lines = []
        for s, _x, _y, _h, _ in sorted(layout_texts(doc.layouts.get(name)), key=lambda t: (-round(t[2], 1), t[1])):
            if s and s not in lines:
                lines.append(s)
        if lines:
            out.append(f"[{name}] " + " | ".join(lines))
    for t in d.tables + d.text_tables:
        out.append(f"[tabel {t.tid}] " + " / ".join(" | ".join(str(v) for v in r) for r in t.rows[:40]))
    if d.legends:
        out.append("[legendă] " + " | ".join(sorted({le.label for le in d.legends})))
    return "\n".join(out)


def _clean(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS] + f"\n[… trunchiat; documentul are {len(text):,} caractere]".replace(",", " ")
    return text


class ProjectInfo:
    """Notes and reference documents of one drawing, kept in its cache folder."""

    def __init__(self, cache_dir: Path):
        self.dir = cache_dir / "references"
        self.notes_file = cache_dir / "project_info.txt"

    def notes(self) -> str:
        try:
            return self.notes_file.read_text()
        except OSError:
            return ""

    def set_notes(self, text: str) -> None:
        self.notes_file.write_text(text or "")

    def _index(self) -> list[dict]:
        try:
            return json.loads((self.dir / "index.json").read_text())
        except (OSError, ValueError):
            return []

    def _save(self, items: list[dict]) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "index.json").write_text(json.dumps(items, ensure_ascii=False, indent=1))

    def documents(self) -> list[dict]:
        return self._index()

    def add(self, name: str, data: bytes) -> dict:
        suffix = Path(name).suffix.lower()
        if suffix not in KINDS:
            raise ValueError("Se acceptă PDF, DWG, DXF sau TXT.")
        rid = uuid.uuid4().hex[:8]
        self.dir.mkdir(parents=True, exist_ok=True)
        src = self.dir / f"{rid}{suffix}"
        src.write_bytes(data)
        try:
            text = extract_text(src)
        except Exception as e:
            src.unlink(missing_ok=True)
            raise ValueError(f"Documentul nu a putut fi citit: {e}") from e
        (self.dir / f"{rid}.txt").write_text(text)
        item = {"id": rid, "name": Path(name).name, "kind": KINDS[suffix], "chars": len(text), "preview": text[:300]}
        self._save([*self._index(), item])
        return item

    def remove(self, rid: str) -> None:
        items = self._index()
        if rid not in {i["id"] for i in items} or not re.fullmatch(r"[0-9a-f]{8}", rid):
            raise ValueError("Document necunoscut.")
        for f in self.dir.glob(f"{rid}.*"):
            f.unlink(missing_ok=True)
        self._save([i for i in items if i["id"] != rid])

    def prompt_text(self) -> str:
        """The block added to the AI prompt (empty when there is nothing)."""
        parts = []
        notes = self.notes().strip()
        if notes:
            parts.append("Notes from the user / client answers:\n" + notes)
        for item in self._index():
            try:
                text = (self.dir / f"{item['id']}.txt").read_text()
            except OSError:
                continue
            if text.strip():
                parts.append(f'Reference document "{item["name"]}" ({item["kind"]}):\n{text}')
        return "\n\n".join(parts)
