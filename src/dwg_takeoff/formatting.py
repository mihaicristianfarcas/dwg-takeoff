"""Number formats: plain ("1 610.46") for the AI's view of the drawing, Romanian ("1 610,46") for
everything the user reads."""

from __future__ import annotations


def num(x: float, nd: int = 2) -> str:
    """Thousands separated by spaces, decimal point: 1 610.46"""
    return f"{x:,.{nd}f}".replace(",", " ")


def num_ro(x: float, nd: int = 2) -> str:
    """Romanian format: 1 610,46 (narrow no-break space between thousands)."""
    return f"{x:,.{nd}f}".replace(",", " ").replace(".", ",")


def factor_ro(x) -> str:
    """Compact factor value: 0,15 / 2 / 1,25"""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return str(x)
    return f"{v:.3f}".rstrip("0").rstrip(".").replace(".", ",")
