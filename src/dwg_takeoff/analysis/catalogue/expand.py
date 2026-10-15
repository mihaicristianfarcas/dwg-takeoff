"""Plans name catalogue entries by id; the engine needs filters. `expand_entries` adds each named
entry's filters to the plan (marked with the entry), so the plan can be measured - and later re-
measured - without the catalogue."""

from __future__ import annotations


def entry_index(cat: dict) -> dict[str, dict]:
    return {e["id"]: e for e in cat.get("entries", [])}


def expand_entries(plan: dict, cat: dict) -> tuple[dict, list[str]]:
    """Plan components that name entries get the entries' filters as sources (kept in the plan,
    so it can be re-measured without the catalogue); unknown ids are reported."""
    idx = entry_index(cat)
    issues = []
    for it in plan.get("items", []):
        for c in it.get("components") or []:
            for ek, sk in (("entries", "sources"), ("subtract_entries", "subtract_sources")):
                ids = c.get(ek) or []
                if not ids:
                    continue
                srcs = [x for x in (c.get(sk) or []) if not x.get("entry")]
                for eid in ids:
                    e = idx.get(str(eid).strip().upper())
                    if e is None:
                        issues.append(f"{it.get('label') or it.get('id')}: catalogue entry '{eid}' does not exist.")
                        continue
                    for f in e["filters"]:
                        srcs.append(dict(f, entry=e["id"], entry_key=e["key"]))
                c[sk] = srcs
    return plan, issues
