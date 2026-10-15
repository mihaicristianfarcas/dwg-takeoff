"""DXF document -> `Drawing` (see `model`): the entry point of the CAD reading stage."""

from __future__ import annotations

import re
from pathlib import Path

from ezdxf.document import Drawing as DxfDocument

from .entities import block_name, layer_color, layout_texts, load_doc, use_block_names
from .legends import extract_legends
from .model import Drawing, EmbeddedTable, LayerInfo
from .modelspace import extract_model_space, measurable_count
from .sheets import extract_layouts
from .tables import extract_tables, text_tables
from .units import infer_units


def extract(
    dxf_path: str | Path,
    source_name: str | None = None,
    doc: DxfDocument | None = None,
    unit_override: int | dict | None = None,
) -> Drawing:
    doc = doc or load_doc(dxf_path)
    use_block_names(doc)
    warnings: list[str] = []
    layers = {}
    for layer in doc.layers:
        try:
            desc = (layer.description or "").strip()
        except Exception:
            desc = ""
        layers[layer.dxf.name] = LayerInfo(
            layer.dxf.name,
            layer_color(layer),
            layer.is_on(),
            layer.is_frozen(),
            layer.is_locked(),
            layer.dxf.get("linetype", ""),
            None if layer.rgb is not None else (abs(layer.color) or 7),
            desc,
        )
    space = "Model"
    notes: dict = {"callouts": [], "dimensions": []}
    features = extract_model_space(doc, layers, warnings, notes=notes)
    if not any(f.kind != "text" for f in features):
        # drawings made directly on a sheet: measure the sheet with the most geometry
        sheets = [(measurable_count(doc.layouts.get(n)), n) for n in doc.layouts.names() if n != "Model"]
        sheets = [x for x in sheets if x[0] > 0]
        if sheets:
            space = max(sheets)[1]
            notes = {"callouts": [], "dimensions": []}
            features = extract_model_space(doc, layers, warnings, doc.layouts.get(space), notes=notes)
            warnings.append(f"Model space has no geometry; the drawing is measured on sheet '{space}'.")
    header_units = doc.header.get("$INSUNITS", 0)
    measurement, lunits = doc.header.get("$MEASUREMENT"), doc.header.get("$LUNITS")
    try:
        dims = dimension_pairs(doc.modelspace() if space == "Model" else doc.layouts.get(space), doc)
    except Exception:
        dims = []
    ui = infer_units(header_units, features, measurement, lunits, unit_override, dims)
    xrefs = sorted({b.name for b in doc.blocks if b.block and b.block.is_xref})
    ttables: list[EmbeddedTable] = []
    for name in [space] + [n for n in doc.layouts.names() if n != space]:
        try:  # schedules / balances drawn as text, on sheets and in the measured space
            for t in text_tables(layout_texts(doc.layouts.get(name)), name):
                same = next((o for o in ttables if o.rows == t.rows), None)
                if same is not None:
                    same.layouts.append(name)
                else:
                    t.tid = f"X{len(ttables) + 1}"
                    ttables.append(t)
        except Exception:
            pass
    legends = extract_legends(doc, layers, features if space == "Model" else None)
    return Drawing(
        source_name=source_name or Path(dxf_path).name,
        dxf_path=str(dxf_path),
        dxf_version=doc.dxfversion,
        units=ui.label,
        unit_scale=ui.scale,
        layers=layers,
        features=features,
        legends=legends,
        layouts=extract_layouts(doc, ui.scale),
        tables=extract_tables(doc),
        xrefs=xrefs,
        warnings=sorted(set(warnings)),
        space=space,
        unit_info=ui.to_dict() | {"measurement": measurement, "lunits": lunits, "dims": dims},
        text_tables=ttables[:12],
        callouts=notes["callouts"],
        dimensions=notes["dimensions"],
        block_descriptions=_block_descriptions(doc),
        # samples of fills, outlines and symbols are left out of every measurement; line samples are
        # not (a short line next to a text is too often part of the drawing itself)
        legend_handles={le.handle for le in legends if le.handle and le.sample != "line"},
    )


def _block_descriptions(doc: DxfDocument) -> dict[str, str]:
    out = {}
    for b in doc.blocks:
        try:
            d = (b.block.dxf.get("description", "") or "").strip()
        except Exception:
            continue
        if d and not b.name.startswith("*"):
            out[block_name(b.name)] = d[:200]
    return out


_DIM_NUMBER = re.compile(r"^\s*[^\d-]{0,3}(-?\d+(?:[.,]\d+)?)")


def dimension_pairs(space, doc: DxfDocument, limit: int = 300) -> list[tuple[float, float]]:
    """(drawn length, displayed value) of linear dimensions: their ratio is the true scale of the
    drawing (a 5.00 label on a 5000-unit line means the drawing is in millimetres)."""
    out = []
    for d in space.query("DIMENSION"):
        if len(out) >= limit:
            break
        try:
            if (d.dimtype & 0x0F) not in (0, 1):  # rotated / aligned linear dimensions only
                continue
            m = float(d.get_measurement())
            shown = d.dxf.get("text", "")
            if not shown or "<>" in shown:
                blk = doc.blocks.get(d.dxf.get("geometry", "")) if d.dxf.get("geometry") else None
                shown = (
                    next((e.plain_text() for e in blk if e.dxftype() in ("MTEXT", "TEXT")), "")
                    if blk is not None
                    else ""
                )
            mt = _DIM_NUMBER.match(shown or "")
            if m > 0 and mt:
                v = float(mt.group(1).replace(",", "."))
                if v > 0:
                    out.append((m, v))
        except Exception:
            continue
    return out


def apply_units(drawing: Drawing, override: int | dict | None) -> Drawing:
    """Re-derive the unit scale (header / inferred / user override) without re-extracting."""
    ui0 = drawing.unit_info or {}
    ui = infer_units(
        ui0.get("header_code", 0),
        drawing.features,
        ui0.get("measurement"),
        ui0.get("lunits"),
        override,
        ui0.get("dims"),
    )
    factor = ui.scale / drawing.unit_scale if drawing.unit_scale else 1.0
    for lo in drawing.layouts:
        for vp in lo.viewports:
            if vp.denominator:
                vp.denominator *= factor
    drawing.unit_scale = ui.scale
    drawing.units = ui.label
    drawing.unit_info = ui.to_dict() | {k: ui0.get(k) for k in ("measurement", "lunits", "dims")}
    return drawing
