"""Second pass over a plan: the model sees what the engine measured for each of its sources (entity
counts, block names, symbol sizes, overlaps, unit mismatches) and corrects the items that are
wrong, the way a senior estimator checks a takeoff before it leaves the office. When the plan is
right the answer is a short "ok", so the check costs little time.
"""

from __future__ import annotations

import copy
import json
import re
from collections import Counter

from ..engine.executor import resolve_source
from ..formatting import num
from .schema import PLAN_SCHEMA

ITEM_SCHEMA = PLAN_SCHEMA["properties"]["items"]["items"]

REVIEW_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["verdict", "notes", "items", "remove_ids", "general_notes", "questions_for_user"],
    "properties": {
        "verdict": {"type": "string", "enum": ["ok", "revised"]},
        "notes": {
            "type": "array",
            "items": {"type": "string"},
            "description": "What was checked or changed and why, one short sentence each.",
        },
        "items": {
            "type": "array",
            "items": ITEM_SCHEMA,
            "description": "Only corrected (same id) or added items, complete; [] when the plan is right.",
        },
        "remove_ids": {"type": "array", "items": {"type": "string"}},
        "general_notes": {
            "type": ["array", "null"],
            "items": {"type": "string"},
            "description": "null = keep; otherwise the complete new list.",
        },
        "questions_for_user": {
            "type": ["array", "null"],
            "items": {"type": "string"},
            "description": "null = keep; otherwise the complete new list.",
        },
    },
}

REVIEW_RULES = """\
=== REVIEW ===
Above is the plan you produced for this request and what the engine measured with it. Check it
the way a senior estimator checks a takeoff before it is sent, using the measured results, the
digest (and the lookup files if needed). Look for real errors only:
- a source that matched nothing, or matched entities that are not the requested element (another
  symbol's blocks, a colour/pattern group of a different surface, groups whose size does not fit
  the element, a layer outside the site);
- a requested element, or a plausible candidate group from the digest, that is missing;
- the same surface, curb or concrete counted twice (see CHECKS), or structural assumptions that
  contradict each other between items;
- a final unit that differs from the requested unit, a factor with the wrong unit or origin;
- an implausible magnitude for what the drawing shows.
If nothing is wrong: verdict "ok", items [], remove_ids [], general_notes null, questions_for_user
null - do not rephrase, reorder or restyle anything. Otherwise verdict "revised": return in
`items` only the corrected or added items, complete (an item with an existing id replaces it),
list ids to drop in `remove_ids`, and say in `notes` what you changed and why (one short sentence
each, in the client's language)."""


def _src_text(src: dict) -> str:
    if src.get("entry"):
        return f"entry {src['entry']}"
    keys = ("layer", "kinds", "pattern", "color", "block", "table_object")
    parts = [f"{k}={src[k] if k != 'kinds' else ','.join(src[k])}" for k in keys if src.get(k)]
    if src.get("handles"):
        parts.append(f"handles={len(src['handles'])}")
    return " ".join(parts) or "(empty source)"


_SIZE = re.compile(r"([\d.]+) × ([\d.]+) m")


def _matched(src: dict, comp: dict, drawing, by_layer, regions, transform) -> str:
    region = regions.get(comp.get("region")) if comp.get("region") else None
    feats = resolve_source(src, drawing, by_layer, region, [], transform)
    if not feats:
        return "matches NOTHING"
    s = drawing.unit_scale
    kinds = Counter(getattr(f, "kind", "?") for f in feats)
    out = f"{len(feats)} entities (" + ", ".join(f"{k} {n}" for k, n in kinds.most_common()) + ")"
    area = sum(getattr(f, "area", 0) or 0 for f in feats) * s * s
    length = sum(getattr(f, "length", 0) or 0 for f in feats) * s
    if area > 0 and comp.get("measure") in ("area", "perimeter"):
        out += f", drawn area {num(area)} m²"
    if length > 0 and comp.get("measure") in ("length", "perimeter", "enclosed_area", "strip_area"):
        out += f", drawn length {num(length)} m"
    blocks = Counter(f.block for f in feats if getattr(f, "kind", "") == "block" and f.block)
    if blocks:
        out += "; blocks " + ", ".join(f"{b} ×{n}" for b, n in blocks.most_common(6))
        if len(blocks) > 6:
            out += f" (+{len(blocks) - 6} more names)"
    if any(not getattr(f, "visible", True) for f in feats):
        out += "; on a frozen/off layer"
    return out


def _group_sizes(comp: dict) -> str:
    sizes = []
    for row in comp.get("evidence") or []:
        m = _SIZE.search(row.get("note") or "")
        if m:
            sizes.append(max(float(m.group(1)), float(m.group(2))))
    if not sizes:
        return ""
    sizes.sort()
    q = lambda p: sizes[min(len(sizes) - 1, int(p * (len(sizes) - 1) + 0.5))]  # noqa: E731
    return f"group size (largest side) min {q(0):.2f} / median {q(0.5):.2f} / max {q(1):.2f} m"


def measurement_report(
    plan: dict, result: dict, drawing, regions: dict, transform=None, issues: list[str] | None = None
) -> str:
    """Plain-text account of what the engine measured for every item, component and source."""
    by_layer = drawing.by_layer()
    plan_items = {it.get("id"): it for it in plan.get("items", [])}
    lines = []
    for it in result.get("items", []):
        pit = plan_items.get(it.get("id"), {})
        val = "no value" if it.get("value") is None else f"{num(it['value'])} {it['unit']}"
        lines.append(
            f"[{it['id']}] {it.get('label')}: {val} (requested unit {pit.get('unit', '?')}, status {it.get('status')})"
        )
        pcs = pit.get("components") or []
        for ci, c in enumerate(it.get("components", [])):
            pc = pcs[ci] if ci < len(pcs) else {}
            st = c.get("stats") or {}
            extra = []
            if "raw_sum" in st and c["measure"] in ("area", "length", "perimeter"):
                extra.append(f"raw drawn sum {num(st['raw_sum'])}")
            if c["measure"] == "count_groups":
                extra.append(_group_sizes(c))
            if c["measure"] == "enclosed_area" and "faces" in st:
                extra.append(f"{st['faces']} closed faces")
            lines.append(
                f'  component {ci + 1} "{c["label"]}" {c["measure"]}: {c["formula"]}'
                + (f" [{'; '.join(e for e in extra if e)}]" if any(extra) else "")
            )
            for si, src in enumerate(pc.get("sources") or []):
                lines.append(
                    f"    source {si + 1}: {_src_text(src)} -> "
                    f"{_matched(src, pc, drawing, by_layer, regions, transform)}"
                )
            for si, src in enumerate(pc.get("subtract_sources") or []):
                lines.append(
                    f"    subtract {si + 1}: {_src_text(src)} -> "
                    f"{_matched(src, pc, drawing, by_layer, regions, transform)}"
                )
            for w in dict.fromkeys(c.get("warnings") or []):
                lines.append(f"    engine warning: {w}")
        for w in it.get("warnings") or []:
            lines.append(f"  item warning: {w}")
    if result.get("checks"):
        lines.append("CHECKS")
        lines += [f"  {ch['message']}" for ch in result["checks"]]
    if issues:
        lines.append("PLAN ISSUES")
        lines += [f"  {i}" for i in issues]
    return "\n".join(lines)


def plan_json(plan: dict) -> str:
    """The plan as the model wrote it: catalogue ids, without the filters they were expanded to."""
    clean = copy.deepcopy({k: v for k, v in plan.items() if not k.startswith("_")})
    for it in clean.get("items", []):
        for c in it.get("components") or []:
            for k in ("sources", "subtract_sources"):
                c[k] = [x for x in c.get(k) or [] if not x.get("entry")]
    return json.dumps(clean, ensure_ascii=False)


def review_text(plan: dict | None, report: str) -> str:
    """The review turn that follows the original prompt (same prefix, so it is served from cache).
    Chat backends pass plan=None: the plan is already in the conversation as the model's answer."""
    head = "=== YOUR PLAN ===\n" + plan_json(plan) + "\n\n" if plan is not None else ""
    return head + "=== WHAT THE ENGINE MEASURED ===\n" + report + "\n\n" + REVIEW_RULES + "\n"


def apply_review(plan: dict, review: dict) -> tuple[dict, list[str]]:
    """The plan with the reviewed items replaced / added / removed, and the ids that changed."""
    out = copy.deepcopy(plan)
    if review.get("verdict") != "revised":
        return out, []
    items = out.get("items", [])
    index = {it.get("id"): i for i, it in enumerate(items)}
    changed = []
    for new in review.get("items") or []:
        iid = new.get("id")
        if iid in index:
            if items[index[iid]] != new:
                items[index[iid]] = new
                changed.append(iid)
        else:
            index[iid] = len(items)
            items.append(new)
            changed.append(iid)
    drop = set(review.get("remove_ids") or []) & set(index)
    if drop:
        items = [it for it in items if it.get("id") not in drop]
        changed += sorted(drop)
    out["items"] = items
    for key in ("general_notes", "questions_for_user"):
        if review.get(key) is not None:
            out[key] = review[key]
    return out, changed
