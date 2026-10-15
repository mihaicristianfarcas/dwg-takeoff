"""Legends: a swatch (hatch, outline, line sample or symbol) with its label just to the right, on
sheets and in model space."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from ezdxf.document import Drawing as DxfDocument

from .entities import bbox, block_name, entity_color, layout_texts
from .model import Feature, LayerInfo, LegendEntry

LEGEND_TYPES = ("HATCH", "MPOLYGON", "SOLID", "LWPOLYLINE", "LINE", "INSERT")


@dataclass
class _Swatch:
    kind: str  # hatch | line | block
    bounds: tuple[float, float, float, float]
    layer: str
    pattern: str | None
    block: str | None
    color: str | None
    handle: str | None = None


def _sheet_swatches(entities, layers: dict):
    for e in entities:
        t = e.dxftype()
        if t not in LEGEND_TYPES:
            continue
        b = bbox([e])
        if b is None:
            continue
        bounds = (b.extmin.x, b.extmin.y, b.extmax.x, b.extmax.y)
        layer = e.dxf.layer
        color = entity_color(e, layers, layer)[0]
        if t in ("HATCH", "MPOLYGON", "SOLID"):
            pattern = "SOLID" if t == "SOLID" or e.dxf.get("solid_fill", 0) else e.dxf.get("pattern_name")
            yield _Swatch("hatch", bounds, layer, pattern, None, color)
        elif t == "INSERT":
            yield _Swatch("block", bounds, layer, None, block_name(e.dxf.name), color)
        else:
            yield _Swatch("line", bounds, layer, None, None, color)


def _feature_swatches(features: list[Feature]):
    """Swatch candidates from already extracted model-space features (no re-reading of blocks)."""
    block_bounds: dict[str, list[float]] = {}
    for f in features:
        if f.nested and f.kind != "text":
            b = f.geom.bounds
            bb = block_bounds.setdefault(f.handle, [b[0], b[1], b[2], b[3]])
            bb[0], bb[1], bb[2], bb[3] = min(bb[0], b[0]), min(bb[1], b[1]), max(bb[2], b[2]), max(bb[3], b[3])
    for f in features:
        if f.nested:
            continue
        if f.kind in ("hatch", "solid"):
            yield _Swatch("hatch", f.geom.bounds, f.layer, f.pattern, None, f.color, f.handle)
        elif f.kind == "line" or (f.kind == "closed" and f.dxftype in ("LWPOLYLINE", "POLYLINE")):
            yield _Swatch("line", f.geom.bounds, f.layer, None, None, f.color, f.handle)
            if f.kind == "closed":  # a surface sample drawn as an outline (a "Building" box)
                yield _Swatch("outline", f.geom.bounds, f.layer, None, None, f.color, f.handle)
        elif f.kind == "block" and f.handle in block_bounds:
            yield _Swatch("block", tuple(block_bounds[f.handle]), f.layer, None, f.block, f.color, f.handle)


def _same_column(a: tuple, b: tuple) -> bool:
    """Two swatch candidates of one model-space legend column: same kind, labels aligned, swatches
    aligned (fills / outlines: same left edge and width; symbols: same axis)."""
    x0, th, w0, le, cx0, lx0, k0 = a
    x1, _, w1, le1, cx1, lx1, k1 = b
    if le1 is le or k1 != k0 or abs(lx1 - lx0) > 1.0 * th:
        return False
    if k0 == "block":
        return abs(cx1 - cx0) <= 2.0 * th
    return abs(x1 - x0) <= 0.6 * th and abs(w1 - w0) <= 0.3 * max(w0, w1)


def _legend_entries(layout_name: str, swatches, texts, column_only: bool) -> list[LegendEntry]:
    """Legend swatches (small hatch / line sample / symbol) with a label just to their right.

    Sizes are judged relative to the label's text height, so the same rules work on sheets in
    millimetres or inches and in model space at any scale. In model space (`column_only`) an
    entry also needs siblings aligned in the same column - a single hatched area next to a text
    on the plan is not a legend."""
    if not texts:
        return []
    hmax = max(h for *_, h, _ in texts) or 1.0
    cell = 12 * hmax
    grid: dict[tuple[int, int], list[int]] = {}
    for i, (_, x, y, _h, _) in enumerate(texts):
        grid.setdefault((int(x // cell), int(y // cell)), []).append(i)
    found = []
    for sw in swatches:
        x0, y0, x1, y1 = sw.bounds
        w, h = x1 - x0, y1 - y0
        if max(w, h) > 20 * hmax or max(w, h) <= 0:
            continue
        cy = (y0 + y1) / 2
        gx, gy = int(x1 // cell), int(cy // cell)
        best = None
        for cx in (gx - 1, gx, gx + 1):
            for cyy in (gy - 1, gy, gy + 1):
                for i in grid.get((cx, cyy), ()):
                    label, x, y, th, _ = texts[i]
                    if not th:
                        continue
                    if sw.kind in ("hatch", "outline"):
                        ok = max(w, h) <= 18 * th and w * h <= 120 * th * th and max(w, h) >= 0.2 * th
                    elif sw.kind == "block":
                        ok = max(w, h) <= 7 * th
                    else:
                        ok = 1.2 * th <= w <= 14 * th and h <= 0.8 * th
                    if not ok:
                        continue
                    dx, dy = x - x1, abs(y - cy)
                    # model-space legends often leave a wide gap before the label; their column
                    # structure (below) keeps that from matching texts next to the plan
                    # (line samples stay tight: equipment and furniture drawn as short lines next
                    # to room names look like a column of line samples)
                    gap = 10 if not column_only else (6 if sw.kind == "line" else 16)
                    if dx < -0.4 * th or dx > gap * th or dy > max(h * 0.6, th * 0.9):
                        continue
                    score = dx + 4 * dy
                    if best is None or score < best[0]:
                        best = (score, label, th, x)
        if not best:
            continue
        label = best[1]
        if len(label) < 3 or len(label) > 120 or label.lower().startswith("legend"):
            continue
        if column_only and sum(ch.isalpha() for ch in label) < max(3, len(label) // 2):
            continue  # elevations, slopes, dimensions next to symbols are not legend labels
        sample = "hatch" if sw.kind == "outline" else sw.kind
        found.append(
            (
                x0,
                best[2],
                w,
                LegendEntry(
                    layout_name,
                    label,
                    sample,
                    sw.layer,
                    sw.pattern,
                    sw.block,
                    sw.color,
                    sw.handle if column_only else None,
                ),
                (x0 + x1) / 2,
                best[3],
                sw.kind,
            )
        )
    if column_only:
        # a model-space legend is a column of at least three swatches of the same kind with their
        # labels aligned: fills / outlines of the same width, symbols (any size) on one axis
        kept = [a[3] for a in found if sum(1 for b in found if _same_column(a, b)) >= 2]
        # a line sample is one line (two at most) per label; more is a drawing next to a text
        per_label = Counter(le.label for le in kept if le.sample == "line")
        return [le for le in kept if le.sample != "line" or per_label[le.label] <= 2]
    return [o[3] for o in found]


def _feature_texts(features: list[Feature]):
    out = []
    for f in features:
        if f.kind == "text" and f.text and f.text_height:
            for i, line in enumerate(f.text.split("\n")):
                if line.strip():
                    out.append(
                        (
                            line.strip(),
                            f.geom.x,
                            f.geom.y + f.text_height / 2 - i * 5 / 3 * f.text_height,
                            f.text_height,
                            f.layer,
                        )
                    )
    return out


def extract_legends(
    doc: DxfDocument, layers: dict[str, LayerInfo], features: list[Feature] | None = None
) -> list[LegendEntry]:
    """Legends on sheets, plus (given the extracted model-space `features`) legends drawn in
    model space."""
    out: list[LegendEntry] = []
    seen = set()

    def sheet(layout):
        return lambda: (_sheet_swatches(layout, layers), layout_texts(layout))

    spaces = [(n, sheet(doc.layouts.get(n)), False) for n in doc.layouts.names() if n != "Model"]
    if features is not None:
        spaces.append(("Model", lambda: (_feature_swatches(features), _feature_texts(features)), True))
    for name, get, column_only in spaces:
        try:
            swatches, texts = get()
            entries = _legend_entries(name, swatches, texts, column_only)
        except Exception:
            continue
        for le in entries:
            key = (
                le.label,
                le.layer,
                le.pattern,
                le.block,
                le.sample,
                le.color if le.sample == "hatch" else None,
                le.handle,
            )
            if key not in seen:
                seen.add(key)
                out.append(le)
    return out
