"""Plain-language names of display colours ("dark green"), for the AI and the UI."""

from __future__ import annotations


def color_name(hexc: str | None) -> str:
    """Name of a "#rrggbb" colour: grey shades by brightness, hues by angle, light / dark variants."""
    if not hexc or len(hexc) != 7:
        return "?"
    r, g, b = (int(hexc[i : i + 2], 16) / 255 for i in (1, 3, 5))
    mx, mn = max(r, g, b), min(r, g, b)
    v, sat = mx, (mx - mn) / mx if mx else 0
    if sat < 0.18:
        if v < 0.2:
            return "black"
        if v < 0.45:
            return "dark grey"
        if v < 0.75:
            return "grey"
        return "light grey" if v < 0.93 else "white"
    d = mx - mn
    if mx == r:
        h = (60 * ((g - b) / d)) % 360
    elif mx == g:
        h = 60 * ((b - r) / d) + 120
    else:
        h = 60 * ((r - g) / d) + 240
    if 15 <= h < 45 and v < 0.62:
        name = "brown"
    else:
        hues = (
            (15, "red"),
            (42, "orange"),
            (68, "yellow"),
            (90, "yellow-green"),
            (160, "green"),
            (200, "cyan"),
            (255, "blue"),
            (290, "purple"),
            (345, "magenta"),
            (361, "red"),
        )
        name = next(n for limit, n in hues if h < limit)
    if v < 0.45 and name != "brown":
        return "dark " + name
    if sat < 0.45 and v > 0.8:
        return "light " + name
    return name


def color_label(hexc: str | None, aci: int | None = None) -> str:
    """ "dark green #1f7f00 ACI 94" """
    return f"{color_name(hexc)} {hexc}" + (f" ACI {aci}" if aci else "")
