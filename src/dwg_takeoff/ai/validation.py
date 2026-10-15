"""Checking a plan against the drawing before it is measured: catalogue ids become engine filters,
and filters naming layers, patterns, colours or table objects the drawing lacks are reported (the
model gets one chance to correct them)."""

from __future__ import annotations

from ..analysis.catalogue import expand_entries
from ..cad.model import Drawing
from .request import PlanRequest


def prepare_plan(plan: dict, req: PlanRequest) -> list[str]:
    """Turn catalogue ids into engine sources (in place) and list what does not exist."""
    issues = []
    cat = (req.digest or {}).get("catalogue")
    if cat:
        plan, issues = expand_entries(plan, cat)
    return issues + validate_plan(plan, req.drawing)


def validate_plan(plan: dict, drawing: Drawing) -> list[str]:
    """Problems a plan has against the drawing (unknown layers, patterns, table objects...)."""
    issues = []
    layers = {f.layer for f in drawing.features}
    lower = {name.lower(): name for name in layers}
    patterns: dict[str, set] = {}
    colors: dict[str, set] = {}
    for f in drawing.features:
        if f.pattern:
            patterns.setdefault(f.layer, set()).add(f.pattern.lower())
        if f.color:
            colors.setdefault(f.layer, set()).add(f.color.lower())
    tables = {o.strip().lower() for t in drawing.tables for o in t.objects}
    if not isinstance(plan.get("items"), list) or not plan["items"]:
        return ["The plan has no items."]
    for it in plan["items"]:
        label = it.get("label") or it.get("id")
        for c in it.get("components") or []:
            for src in (c.get("sources") or []) + (c.get("subtract_sources") or []):
                if src.get("entry"):
                    continue  # expanded from a catalogue entry: an exact selection
                layer = src.get("layer")
                if src.get("table_object"):
                    if src["table_object"].strip().lower() not in tables:
                        issues.append(f"{label}: table object '{src['table_object']}' does not exist.")
                    continue
                if not layer:
                    issues.append(f"{label}: a source has neither a layer nor a table_object.")
                    continue
                real = layer if layer in layers else lower.get(layer.lower())
                if real is None:
                    issues.append(f"{label}: layer '{layer}' does not exist (use the exact name from the digest).")
                    continue
                pat = src.get("pattern")
                if pat and pat.lower() not in patterns.get(real, set()):
                    issues.append(f"{label}: layer '{real}' has no hatch with pattern '{pat}'.")
                col = src.get("color")
                if col and col.strip().lower() not in colors.get(real, set()):
                    issues.append(f"{label}: layer '{real}' has no entity with colour '{col}'.")
    return issues
