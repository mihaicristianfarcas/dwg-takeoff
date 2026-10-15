"""Labels the user gives catalogue entries, stored per drawing by the entries' stable keys."""

from __future__ import annotations

import json
from pathlib import Path

from ..vocabulary import CATEGORIES


class Labels:
    """User labels of catalogue entries, kept in the drawing's cache folder by entry key."""

    def __init__(self, cache_dir: Path):
        self.file = Path(cache_dir) / "labels.json"

    def all(self) -> dict[str, dict]:
        try:
            return json.loads(self.file.read_text())
        except (OSError, ValueError):
            return {}

    def set(self, key: str, label: str | None, category: str | None) -> dict:
        data = self.all()
        label = (label or "").strip()[:120]
        if category and category not in CATEGORIES:
            raise ValueError(f"Categorie necunoscută: {category}")
        if label or category:
            data[key] = {"label": label, "category": category or None}
        else:
            data.pop(key, None)
        tmp = self.file.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1))
        tmp.replace(self.file)
        return data.get(key, {})


def with_labels(cat: dict, labels: dict[str, dict]) -> list[dict]:
    """Entries with their effective label and category (user > legend > callout > text; the
    category from the user, else the vocabulary)."""
    out = []
    for e in cat.get("entries", []):
        e = dict(e)
        u = labels.get(e["key"]) or {}
        top = (e.get("vocab") or [{}])[0]
        e["category"] = u.get("category") or top.get("category")
        e["category_source"] = "user" if u.get("category") else ("vocabulary" if top else "")
        e["label"] = u.get("label") or e.get("auto_label") or ""
        e["label_source"] = "user" if u.get("label") else e.get("auto_label_source", "")
        out.append(e)
    return out
