"""The catalogue as text: one line per entry for the AI prompt (format: the dwg-catalogue skill),
and as CSV for lookups."""

from __future__ import annotations

import csv
from pathlib import Path

from ...formatting import num
from .entry import sort_key
from .labels import with_labels

_WHAT = {
    "surface": "fill",
    "outline": "outlines",
    "linear": "lines",
    "block": "block",
    "nested_block": "block in blocks",
    "table": "table footprint",
    "part": "one surface",
}


def entry_line(e: dict, has_site: bool) -> str:
    """One compact line per entry for the AI prompt."""
    if e["kind"] == "part":
        line = f"  {e['id']} one surface {num(e['area'])} m²" + ("" if e.get("visible", True) else " HIDDEN")
        if e.get("label"):
            line += f' | "{e["label"]}"' + (" (user)" if e.get("label_source") == "user" else "")
        if e.get("category"):
            line += f" | ={e['category']}" + (" (user)" if e.get("category_source") == "user" else "")
        return line
    parts = [e["id"]] + ([_WHAT[e["kind"]]] if e["kind"] in ("nested_block", "table") else [])
    if e.get("layer"):
        parts.append(f"'{e['layer']}'")
    if e.get("in_block"):
        parts.append(f"inside block '{e['in_block']}'")
    if e.get("pattern"):
        parts.append(e["pattern"])
    if e.get("color") and (e["kind"] in ("surface", "outline", "linear") or e.get("split_color")):
        parts.append(e.get("color_name") or e["color"])
    if e.get("block") and e["kind"] in ("block", "nested_block", "table"):
        parts.append(f"'{e['block']}'")
    n = e["n"]
    if has_site and e.get("n_site") is not None:
        out = n - e["n_site"]
        parts.append(
            (f"×{e['n_site']}" + (f" (+{out} outside site)" if out else ""))
            if e["n_site"]
            else f"×{n} all OUTSIDE site"
        )
    else:
        parts.append(f"×{n}")
    if e.get("area") is not None and e["measure"] == "area":
        parts.append(f"{num(e['area'])} m²")
    if e.get("length") is not None and e["kind"] == "linear":
        parts.append(
            f"{num(e['length'])} m"
            + (f" ({num(e['length_dedup'])} m without duplicate traces)" if e.get("length_dedup") else "")
        )
    if e.get("width_m"):
        parts.append(f"width {e['width_m']} m")
    if e.get("size_m"):
        parts.append(f"symbol {e['size_m']} m")
    if not e.get("visible", True):
        parts.append("HIDDEN")
    extra = []
    if e.get("label"):
        extra.append(f'"{e["label"]}" ({e.get("label_source")})')
    if e.get("category"):
        extra.append(f"={e['category']}" + (" (user)" if e.get("category_source") == "user" else ""))
    for k, name, n in (("legend", "legend", 4), ("callouts", "callout", 3), ("texts", "texts", 4), ("dims", "dims", 3)):
        vals = [v.replace("\n", " ") for v in e.get(k) or [] if v != e.get("label")]
        if vals:
            extra.append(f"{name} " + "; ".join(f'"{v}"' for v in vals[:n]))
    if e.get("attributes"):
        extra.append(
            "attr " + "; ".join(f"{k}={'/'.join(map(str, v[:3]))}" for k, v in list(e["attributes"].items())[:4])
        )
    if e.get("descriptions"):
        extra.append("; ".join(e["descriptions"][:2]))
    sym = {"same surface": "=", "inside": "⊂", "contains": "⊃", "mostly overlaps": "≈"}
    dups = [f"{sym.get(d['relation'], '~')}{d['id']}" for d in e.get("duplicates") or [] if d.get("id")]
    if dups:
        extra.append("dup " + " ".join(dups[:3]))
    for d in e.get("edges") or []:
        extra.append(
            f"edged by {d['id']} '{d['layer']}'"
            + "".join(f' "{x}"' for x in d.get("legend") or [])
            + f" {d['share']:.0%}"
        )
    if e.get("edge_of"):
        extra.append("edges " + " ".join(f"{d['id']} {d['share']:.0%}" for d in e["edge_of"][:3]))
    return " ".join(parts) + (" | " + " | ".join(extra) if extra else "")


def catalogue_text(cat: dict, labels: dict[str, dict], max_entries: int = 300) -> str:
    entries = with_labels(cat, labels)
    has_site = cat.get("site", False)

    def rank(e):
        site = (e.get("n_site") or 0) > 0 if has_site else True
        named = bool(e.get("label") or e.get("category"))
        return (not site, not named, e.get("in_block") is not None, sort_key(e))

    shown = sorted(entries, key=rank)[:max_entries]
    shown.sort(key=sort_key)
    head = (
        f"CATALOGUE: {len(entries)} entries (format: see the catalogue guide). Quantities are measured "
        f"{'inside the site region' if has_site else 'on the whole drawing (no site region)'}."
    )
    if len(shown) < len(entries):
        head += f" {len(entries) - len(shown)} minor entries are not shown (catalogue.csv / lookup tools)."
    if cat.get("containers"):
        head += (
            " Blocks holding whole drawings, broken down into entries: "
            + ", ".join(f"'{c}'" for c in cat["containers"][:5])
            + "."
        )
    return head + "\n" + "\n".join(entry_line(e, has_site) for e in shown)


def _csv_row(e: dict) -> dict:
    def opt(v):
        return "" if v is None else round(v, 3) if isinstance(v, float) else v

    def joined(values):
        return " | ".join(values or [])

    return {
        "id": e["id"],
        "kind": e["kind"],
        "layer": e["layer"] or "",
        "in_block": e["in_block"] or "",
        "pattern": e["pattern"] or "",
        "color": e["color"] or "",
        "block": e["block"] or "",
        "n": e["n"],
        "n_site": opt(e["n_site"]),
        "area_m2": opt(e["area"]),
        "length_m": opt(e["length"]),
        "length_dedup_m": opt(e["length_dedup"]),
        "count": opt(e["count"]),
        "size_m": e["size_m"] or "",
        "visible": int(e["visible"]),
        "label": e["label"],
        "label_source": e["label_source"],
        "category": e["category"] or "",
        "legend": joined(e["legend"]),
        "callouts": joined(e["callouts"]),
        "texts": joined(e["texts"]),
        "dims": joined(e["dims"]),
        "duplicates": joined(f"{d.get('id')} {d['relation']}" for d in e["duplicates"]),
        "edges": joined(
            [f"edged by {d.get('id')} {d['share']:.0%}" for d in e.get("edges") or []]
            + [f"edges {d.get('id')} {d['share']:.0%}" for d in e.get("edge_of") or []]
        ),
    }


def write_csv(cat: dict, labels: dict, path: Path) -> None:
    """Every entry, one row each: the file Codex may search for entries not shown in the prompt."""
    rows = [_csv_row(e) for e in with_labels(cat, labels)]
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        if rows:
            w.writerow(rows[0])
            w.writerows(r.values() for r in rows)
