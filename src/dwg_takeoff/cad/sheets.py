"""Sheets (paper-space layouts): titles, long notes and the viewports onto model space."""

from __future__ import annotations

import math
import re

from ezdxf.document import Drawing as DxfDocument

from .model import LayoutInfo, ViewportInfo

TITLE_WORDS = re.compile(
    r"\bplan|sec[tț]iune|detaliu|profil|releveu|fa[tț]ad[aă]|\bsite\b|layout|floor|"
    r"elevation|section|detail|parter|etaj|subsol|acoperi[sș]",
    re.I,
)
TITLE_LAYERS = re.compile(r"cartus|cartuș|title|indicator|stamp|tb\b|frame|chenar", re.I)
PAPER_UNIT_M = {0: 0.0254, 1: 0.001}  # plot paper units: inches / millimetres


def extract_layouts(doc: DxfDocument, unit_scale: float = 1.0) -> list[LayoutInfo]:
    infos = []
    for name in doc.layouts.names():
        if name == "Model":
            continue
        layout = doc.layouts.get(name)
        texts = []
        for e in layout:
            t = e.dxftype()
            if t in ("TEXT", "MTEXT"):
                s = (e.plain_text() or "").strip()
                if s:
                    h = e.dxf.get("char_height" if t == "MTEXT" else "height", 0) or 0
                    texts.append((s, h, e.dxf.layer))
        big = sorted(h for _, h, _ in texts)[int(len(texts) * 0.75)] if texts else 0
        titles, notes = [], []
        for s, h, lay in texts:
            if len(s) < 120 and TITLE_WORDS.search(s) and (TITLE_LAYERS.search(lay) or (h and h >= big)):
                titles.append(s)
            elif len(s) > 25:
                notes.append(s)
        try:
            paper_m = PAPER_UNIT_M.get(layout.dxf_layout.dxf.get("plot_paper_units", 1), 0.001)
        except Exception:
            paper_m = 0.001
        vps = []
        for vp in layout.query("VIEWPORT"):
            if vp.dxf.get("status", 1) == 1 and vp.dxf.view_height and abs(vp.dxf.view_height - vp.dxf.height) < 1e-6:
                continue  # the layout's own paper-space viewport
            c = vp.dxf.view_center_point
            tgt = vp.dxf.view_target_point
            tw = math.radians(vp.dxf.get("view_twist_angle", 0.0))
            x = c.x * math.cos(-tw) - c.y * math.sin(-tw) + tgt.x
            y = c.x * math.sin(-tw) + c.y * math.cos(-tw) + tgt.y
            vh = vp.dxf.view_height
            if not vh or not vp.dxf.height:
                continue
            scale = vp.dxf.height / vh
            pc = vp.dxf.center
            if abs(scale - 1) < 1e-6 and abs(x - pc.x) < 1e-3 and abs(y - pc.y) < 1e-3:
                continue  # the layout's own paper-space viewport
            denom = (vh * unit_scale) / (vp.dxf.height * paper_m)
            vps.append(
                ViewportInfo(
                    name,
                    vp.dxf.handle,
                    (x, y),
                    vh,
                    vp.dxf.width / scale,
                    vp.dxf.get("view_twist_angle", 0.0),
                    scale,
                    sorted(vp.frozen_layers or []),
                    denom,
                )
            )
        infos.append(LayoutInfo(name, sorted(set(titles)), vps, notes))
    return infos
