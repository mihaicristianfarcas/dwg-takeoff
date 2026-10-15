"""The digest: a compact, factual summary of a drawing for the AI planner and the UI explorer.

It holds only facts read from the drawing - sheets and viewports, legends, tables, notes, texts -
and ends with the element catalogue (`catalogue`), the numbered breakdown the AI chooses from.
`digest_to_text` renders it as the drawing part of the prompt.
"""

from __future__ import annotations

from shapely.prepared import prep

from ..cad.georef import transformed_polygon
from ..cad.model import Drawing, Feature
from ..cad.tables import table_polygon
from ..formatting import num
from .catalogue import build_catalogue, catalogue_text
from .colors import color_label
from .site import focus_region, plot_denominator


def _footprint_context(poly, in_site: dict[str, list[Feature]], max_area: float) -> list[str]:
    """Surfaces (most specific first) that a georeferenced footprint lies on. Entities covering a
    large part of the site (backgrounds, demolition zones) are skipped."""
    hits = []
    for layer, feats in in_site.items():
        for f in feats:
            if (
                f.kind in ("hatch", "solid", "closed")
                and not f.nested
                and f.geom.area < max_area
                and f.geom.intersects(poly)
            ):
                share = f.geom.intersection(poly).area / poly.area if poly.area else 0
                if share > 0.05:
                    hits.append((f.geom.area, f"{layer} ({f.kind}, {100 * share:.0f}%)"))
                    break
    return [h for _, h in sorted(hits)][:6]


def _tables(drawing: Drawing, table_transform, focus, in_site) -> list[dict]:
    out = []
    for t in drawing.tables:
        objs = []
        for name, pts in t.objects.items():
            p = table_polygon(pts)
            o = {
                "object": name,
                "points": [list(x) for x in pts],
                "footprint_area_m2": p.area * drawing.unit_scale**2 if not p.is_empty else None,
                "footprint_perimeter_m": p.length * drawing.unit_scale if not p.is_empty else None,
            }
            if table_transform is not None and not p.is_empty:
                mp = transformed_polygon(p, table_transform)
                c = mp.centroid
                o["model_center"] = [round(c.x, 2), round(c.y, 2)]
                o["inside_site"] = bool(focus and focus["polygon"].contains(c))
                o["lies_on"] = _footprint_context(mp, in_site, 0.25 * focus["polygon"].area if focus else float("inf"))
            objs.append(o)
        out.append(
            {"id": t.tid, "kind": t.kind, "sheets": t.layouts, "title": t.title, "rows": t.rows[:40], "objects": objs}
        )
    return out


def build_digest(drawing: Drawing, table_transform=None) -> dict:
    focus = focus_region(drawing)
    by_layer = drawing.by_layer()
    in_site: dict[str, list[Feature]] = {}
    if focus:
        pf = prep(focus["polygon"])
        for layer, feats in by_layer.items():
            sel = [f for f in feats if pf.contains(f.geom.representative_point())]
            if sel:
                in_site[layer] = sel

    site_texts, seen = [], set()  # texts inside the site region, or of the whole drawing without one
    for layer, feats in (in_site if focus else by_layer).items():
        for f in feats:
            if f.kind == "text" and f.text and (layer, f.text) not in seen and len(site_texts) < 150:
                seen.add((layer, f.text))
                site_texts.append({"layer": layer, "text": f.text[:160]})

    notes = []
    for lo in drawing.layouts:
        for n in lo.notes:
            if n not in notes:
                notes.append(n)

    s = drawing.unit_scale
    return {
        "file": drawing.source_name,
        "dxf_version": drawing.dxf_version,
        "units": drawing.units,
        "unit_scale_to_m": s,
        "unit_info": drawing.unit_info,
        "space": drawing.space,
        "xrefs_missing": drawing.xrefs,
        "warnings": drawing.warnings,
        "sheets": [
            {
                "layout": lo.name,
                "titles": lo.titles,
                "viewports": [
                    {
                        "handle": v.handle,
                        "center": [round(c, 2) for c in v.model_center],
                        "scale": f"1:{round(plot_denominator(v, s)) if plot_denominator(v, s) else '?'}",
                        "twist": round(v.twist_deg, 1),
                        "frozen_layers": v.frozen_layers,
                    }
                    for v in lo.viewports
                ],
            }
            for lo in drawing.layouts
        ],
        "focus_region": None
        if not focus
        else {
            "id": focus["id"],
            "sheets": focus["sheets"],
            "twist_deg": focus["twist_deg"],
            "area_m2": focus["polygon"].area * s**2,
            "bounds": [round(v, 2) for v in focus["polygon"].bounds],
        },
        "legends": [
            {
                "sheet": le.layout,
                "label": le.label,
                "sample": le.sample,
                "layer": le.layer,
                "pattern": le.pattern,
                "block": le.block,
                "color": le.color,
            }
            for le in drawing.legends
        ],
        "text_tables": [
            {"id": t.tid, "sheet": t.layouts[0], "title": t.title, "rows": t.rows[:40]} for t in drawing.text_tables
        ],
        "tables": _tables(drawing, table_transform, focus, in_site),
        "tables_georef": table_transform.to_dict() if table_transform is not None else None,
        "notes": notes[:40],
        "site_texts": site_texts,
        "catalogue": build_catalogue(drawing, focus["polygon"] if focus else None, table_transform),
    }


def digest_to_text(dg: dict, labels: dict | None = None) -> str:
    """The drawing part of the AI prompt. `labels`: the user's labels of catalogue entries."""
    lines = [f"FILE: {dg['file']}  (DXF {dg['dxf_version']}, units: {dg['units']}, all quantities below in m / m²)"]
    ui = dg.get("unit_info") or {}
    if ui.get("evidence"):
        lines.append(f"  units evidence ({ui.get('confidence')} confidence): " + "; ".join(ui["evidence"][:3]))
    if dg.get("space", "Model") != "Model":
        lines.append(f"  NOTE: model space is empty - the geometry below is measured on sheet '{dg['space']}'.")
    if dg["xrefs_missing"]:
        lines.append(f"Unbound external references (content NOT available): {', '.join(dg['xrefs_missing'])}")
    fr = dg.get("focus_region")
    if fr:
        lines.append(
            f"\nSITE REGION 'site': the model window shown by the detailed sheets {fr['sheets']} "
            f"(area of window {num(fr['area_m2'])} m²). Stats marked [site] only count entities inside it."
        )
    lines.append("\nSHEETS (paper-space layouts) and their titles:")
    for s in dg["sheets"]:
        lines.append(f"- {s['layout']}: {'; '.join(s['titles']) or '(no title found)'}")
        for v in s["viewports"]:
            n_fz = len(v["frozen_layers"])
            fz = (
                f"{n_fz} layers frozen in this viewport (e.g. {', '.join(v['frozen_layers'][:6])})"
                if n_fz
                else "no layer frozen in this viewport"
            )
            lines.append(
                f"    viewport {v['handle']} centre {v['center']} scale {v['scale']} twist {v['twist']}°; {fz}"
            )
    lines += _legend_lines(dg)
    lines += _table_lines(dg)
    if dg["notes"]:
        lines.append("\nNOTES / LONG TEXTS on sheets:")
        for n in dg["notes"][:30]:
            lines.append("- " + n.replace("\n", " / ")[:400])
    cat = dg["catalogue"]
    # texts that name an entry are shown on it; levels and numbers say little alone
    used = {x for e in cat.get("entries", []) for k in ("texts", "callouts") for x in e.get(k) or []}
    texts = [
        t
        for t in dg["site_texts"]
        if sum(ch.isalpha() for ch in t["text"]) >= 2
        and t["text"][:60] not in used
        and not any(u.startswith(t["text"][:60]) for u in used)
    ][:80]
    if texts:
        lines.append("\nOTHER TEXTS " + ("inside the site region" if fr else "in the drawing") + " (layer: text):")
        lines.append("; ".join(f"{t['layer']}: {t['text']}" for t in texts))
    lines.append("\n" + catalogue_text(cat, labels or {}))
    return "\n".join(lines)


def _legend_lines(dg: dict) -> list[str]:
    """Legend entries not linked to any catalogue entry (the linked ones are shown on the entries)."""
    linked = {x for e in dg["catalogue"].get("entries", []) for x in e.get("legend") or []}
    legends = [le for le in dg["legends"] if le["label"] not in linked]
    out = [
        f"\nLEGEND ENTRIES: {len(dg['legends'])} found on sheets; {len(dg['legends']) - len(legends)} are linked to "
        "catalogue entries (shown there). Not linked to any entry (sample not drawn as a measurable group):"
    ]
    if not dg["legends"]:
        out.append("- (none found: identify elements by layer names, hatch patterns, colours, block names and texts)")
    for le in legends:
        extra = f" pattern={le['pattern']}" if le["pattern"] else ""
        extra += f" block={le['block']}" if le["block"] else ""
        extra += f" colour={color_label(le['color'])}" if le.get("color") else ""
        out.append(f"- [{le['sheet']}] \"{le['label']}\" <- {le['sample']} on layer '{le['layer']}'{extra}")
    return out


def _table_lines(dg: dict) -> list[str]:
    out = []
    if dg["tables"]:
        out.append("\nTABLES (OLE Excel/Word objects and AutoCAD tables):")
        gr = dg.get("tables_georef")
        if gr:
            out.append(
                f"  Setting-out coordinates are georeferenced to model space: {gr['matched']} table points coincide "
                f"with drawn vertices (RMS {gr['rms_m'] * 1000:.1f} mm), so every table footprint can be located "
                f"and drawn on the plan (shown as 'located at')."
            )
        for t in dg["tables"]:
            out.append(f"- {t['id']} ({t['kind']}, sheets {t['sheets']}): {t['title']}")
            if t["objects"]:
                for o in t["objects"]:
                    fa = o["footprint_area_m2"]
                    out.append(
                        f'    object "{o["object"]}": {len(o["points"])} points {[p[0] for p in o["points"]]}'
                        + (f"; polygon area {num(fa)} m², perimeter {num(o['footprint_perimeter_m'])} m" if fa else "")
                        + (
                            f"; located at {o['model_center']}{'' if o.get('inside_site') else ' (outside site region)'}"
                            f", lies on: {', '.join(o.get('lies_on') or []) or 'no drawn surface'}"
                            if o.get("model_center")
                            else ""
                        )
                    )
            else:
                for r in t["rows"][:25]:
                    out.append("    | " + " | ".join(str(v) for v in r))
    if dg.get("text_tables"):
        out.append("\nTABLES DRAWN AS TEXT (texts aligned in rows, cells separated by |; sheet name or Model):")
        for t in dg["text_tables"]:
            out.append(f"- {t['id']} (sheet {t['sheet']}):")
            for r in t["rows"][:25]:
                out.append("    | " + " | ".join(str(v) for v in r))
    return out
