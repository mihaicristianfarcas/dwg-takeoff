"""Shapely geometry -> the compact JSON the web viewer draws (model coordinates, mm precision)."""

from __future__ import annotations

from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.base import BaseGeometry


def xy(c) -> list[float]:
    return [round(c[0], 3), round(c[1], 3)]


def geom_to_json(g: BaseGeometry | None) -> dict:
    """{"polygons": [[ring, hole...]...], "lines": [[xy...]...], "points": [xy...]}"""
    out = {"polygons": [], "lines": [], "points": []}
    if g is None or g.is_empty:
        return out

    def add(geom):
        if isinstance(geom, Polygon):
            if not geom.is_empty:
                out["polygons"].append(
                    [[xy(c) for c in geom.exterior.coords]] + [[xy(c) for c in r.coords] for r in geom.interiors]
                )
        elif isinstance(geom, LineString):
            if not geom.is_empty:
                out["lines"].append([xy(c) for c in geom.coords])
        elif isinstance(geom, Point):
            out["points"].append(xy((geom.x, geom.y)))
        elif hasattr(geom, "geoms"):
            for sub in geom.geoms:
                add(sub)

    add(g)
    return out


def merge(geoms) -> dict:
    """One JSON object for several geometries."""
    out = {"polygons": [], "lines": [], "points": []}
    for g in geoms:
        j = geom_to_json(g)
        for k in out:
            out[k].extend(j[k])
    return out
