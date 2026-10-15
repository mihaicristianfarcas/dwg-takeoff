"""Read-only lookup tools the API backends can call while planning.

They give the model the same kind of access the Codex backend gets through `features.csv`
(which entities a layer holds, where they are, what texts say), but through a fixed, validated
interface instead of a shell.
"""

from __future__ import annotations

import difflib
import json
import unicodedata

from shapely import STRtree
from shapely.geometry import Point
from shapely.prepared import prep

from ..analysis.catalogue import entry_line, with_labels
from ..cad.model import Drawing, Feature

KINDS = ["hatch", "solid", "closed", "line", "block", "text"]
MAX_LIMIT = 200

TOOL_SPECS = [
    {
        "name": "catalogue_search",
        "description": (
            "Search the drawing's CATALOGUE (also the entries not shown in the prompt) by id, label, "
            "layer, block, legend label, callout, text written inside or category. Returns entries in "
            "the prompt's format; choose them by id in `entries`."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Words to look for, e.g. 'curb', 'S12', 'tree', 'Defpoints'.",
                },
                "limit": {"type": "integer", "description": f"Maximum entries to return (1-{MAX_LIMIT})."},
            },
            "required": ["query", "limit"],
            "additionalProperties": False,
        },
    },
    {
        "name": "layer_entities",
        "description": (
            "List the entities of one layer inside the site region (or the whole drawing when "
            "there is no site region): handle, kind, hatch pattern, block name, area (m²), length (m), "
            "drawn polyline width (m), position, visibility and text. Lines nested inside blocks are "
            "summarised, not listed. Use it to see what a layer really contains before choosing it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "layer": {"type": "string", "description": "Exact layer name from the digest."},
                "kind": {
                    "type": ["string", "null"],
                    "enum": [*KINDS, None],
                    "description": "Only entities of this kind; null for all kinds.",
                },
                "limit": {"type": "integer", "description": f"Maximum rows to return (1-{MAX_LIMIT})."},
            },
            "required": ["layer", "kind", "limit"],
            "additionalProperties": False,
        },
    },
    {
        "name": "search_texts",
        "description": (
            "Find TEXT/MTEXT/attribute texts in model space containing a phrase (case and diacritics "
            "insensitive), with their layer and position. Useful for labels such as 'Terasa 188 mp', "
            "'Loc de joaca', material notes or thicknesses written on the plan."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Phrase to look for, e.g. 'bordura' or 'cm'."},
                "limit": {"type": "integer", "description": f"Maximum rows to return (1-{MAX_LIMIT})."},
            },
            "required": ["query", "limit"],
            "additionalProperties": False,
        },
    },
    {
        "name": "entities_near",
        "description": (
            "List the entities (any layer, not nested inside blocks) closest to a model-space point, "
            "e.g. to see what lies under a georeferenced footprint or next to a label."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "x": {"type": "number", "description": "Model-space X."},
                "y": {"type": "number", "description": "Model-space Y."},
                "radius_m": {"type": "number", "description": "Search radius in metres."},
                "limit": {"type": "integer", "description": f"Maximum rows to return (1-{MAX_LIMIT})."},
            },
            "required": ["x", "y", "radius_m", "limit"],
            "additionalProperties": False,
        },
    },
]


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


class ToolInputError(ValueError):
    pass


class DrawingTools:
    def __init__(self, drawing: Drawing, region=None, catalogue: dict | None = None, labels: dict | None = None):
        self.d = drawing
        self.region = region
        self.catalogue = catalogue
        self.labels = labels or {}
        self._pr = prep(region) if region is not None else None
        self._tree = None
        self._tree_feats: list[Feature] = []

    # -- helpers ------------------------------------------------------------------------
    def _in_region(self, f: Feature) -> bool:
        return self._pr is None or self._pr.contains(f.geom.representative_point())

    def _row(self, f: Feature) -> dict:
        s = self.d.unit_scale
        p = f.geom.representative_point()
        row = {"handle": f.handle, "layer": f.layer, "kind": f.kind}
        if f.pattern:
            row["pattern"] = f.pattern
        if f.color:
            row["color"] = f.color
        if f.block:
            row["block"] = f.block
        if f.attribs:
            row["attributes"] = f.attribs
        if f.area:
            row["area_m2"] = round(f.area * s * s, 3)
        if f.length:
            row["length_m"] = round(f.length * s, 3)
        if f.width:
            row["width_m"] = round(f.width * s, 3)
        row["x"], row["y"] = round(p.x, 2), round(p.y, 2)
        if not f.visible:
            row["hidden"] = True
        if f.nested:
            row["inside_block"] = True
        if f.text:
            row["text"] = f.text[:160]
        return row

    @staticmethod
    def _limit(v) -> int:
        try:
            v = int(v)
        except (TypeError, ValueError):
            raise ToolInputError("limit must be an integer") from None
        return max(1, min(MAX_LIMIT, v))

    # -- tools --------------------------------------------------------------------------
    def layer_entities(self, layer: str, kind: str | None, limit: int) -> dict:
        if not isinstance(layer, str) or not layer:
            raise ToolInputError("layer must be a non-empty string")
        if kind is not None and kind not in KINDS:
            raise ToolInputError(f"kind must be one of {KINDS} or null")
        by_layer = self.d.by_layer()
        name = layer if layer in by_layer else {k.lower(): k for k in by_layer}.get(layer.lower())
        if name is None:
            close = difflib.get_close_matches(layer, list(by_layer), n=5, cutoff=0.6)
            return {"error": f"layer '{layer}' does not exist", "similar_layers": close}
        feats = [f for f in by_layer[name] if self._in_region(f)]
        if kind:
            feats = [f for f in feats if f.kind == kind or (kind == "hatch" and f.kind == "solid")]
        nested_lines = [f for f in feats if f.nested and f.kind == "line"]
        listed = [f for f in feats if not (f.nested and f.kind == "line")]
        listed.sort(key=lambda f: -(f.area or f.length or 0))
        lim = self._limit(limit)
        out = {
            "layer": name,
            "total": len(listed),
            "returned": min(lim, len(listed)),
            "entities": [self._row(f) for f in listed[:lim]],
        }
        if nested_lines:
            out["lines_inside_blocks"] = len(nested_lines)
        return out

    def search_texts(self, query: str, limit: int) -> dict:
        if not isinstance(query, str) or not query.strip():
            raise ToolInputError("query must be a non-empty string")
        q = _norm(query.strip())
        hits = [f for f in self.d.features if f.kind == "text" and q in _norm(f.text)]
        hits.sort(key=lambda f: (not self._in_region(f), f.layer))
        lim = self._limit(limit)
        return {
            "query": query,
            "total": len(hits),
            "texts": [{**self._row(f), "in_site": self._in_region(f)} for f in hits[:lim]],
        }

    def entities_near(self, x: float, y: float, radius_m: float, limit: int) -> dict:
        try:
            x, y, r = float(x), float(y), float(radius_m)
        except (TypeError, ValueError):
            raise ToolInputError("x, y and radius_m must be numbers") from None
        if r <= 0 or r > 500:
            raise ToolInputError("radius_m must be between 0 and 500")
        if self._tree is None:
            self._tree_feats = [f for f in self.d.features if not f.nested and f.kind != "text"]
            self._tree = STRtree([f.geom for f in self._tree_feats])
        p = Point(x, y)
        r_units = r / self.d.unit_scale
        idx = self._tree.query(p.buffer(r_units))
        found = []
        for i in idx:
            f = self._tree_feats[int(i)]
            dist = f.geom.distance(p)
            if dist <= r_units:
                found.append((dist, f))
        found.sort(key=lambda t: t[0])
        lim = self._limit(limit)
        return {
            "total": len(found),
            "entities": [{**self._row(f), "distance_m": round(d * self.d.unit_scale, 2)} for d, f in found[:lim]],
        }

    def catalogue_search(self, query: str, limit: int) -> dict:
        if not isinstance(query, str):
            raise ToolInputError("query must be a string")
        if not self.catalogue:
            return {"total": 0, "entries": [], "note": "this drawing has no catalogue"}
        words = [w for w in _norm(query).split() if w]
        hits = []
        for e in with_labels(self.catalogue, self.labels):
            hay = _norm(
                " ".join(
                    str(x)
                    for x in [
                        e["id"],
                        e.get("label"),
                        e.get("layer"),
                        e.get("block"),
                        e.get("in_block"),
                        e.get("pattern"),
                        e.get("category"),
                        *(e.get("legend") or []),
                        *(e.get("callouts") or []),
                        *(e.get("texts") or []),
                    ]
                    if x
                )
            )
            if all(w in hay for w in words):
                hits.append(e)
        n = self._limit(limit)
        return {"total": len(hits), "entries": [entry_line(e, self.catalogue.get("site", False)) for e in hits[:n]]}

    def call(self, name: str, args: dict) -> str:
        """Run a tool and return a JSON string (errors are returned, not raised, except bad input)."""
        if not isinstance(args, dict):
            raise ToolInputError("arguments must be an object")
        if name == "catalogue_search":
            res = self.catalogue_search(args.get("query"), args.get("limit", 50))
        elif name == "layer_entities":
            res = self.layer_entities(args.get("layer"), args.get("kind"), args.get("limit", 50))
        elif name == "search_texts":
            res = self.search_texts(args.get("query"), args.get("limit", 50))
        elif name == "entities_near":
            res = self.entities_near(args.get("x"), args.get("y"), args.get("radius_m"), args.get("limit", 30))
        else:
            raise ToolInputError(f"unknown tool '{name}'")
        return json.dumps(res, ensure_ascii=False)


def describe_call(name: str, args: dict) -> str:
    """Short Romanian description of a lookup, for the progress feed."""
    if name == "catalogue_search":
        return f"Caută în catalogul planșei: „{args.get('query')}”"
    if name == "layer_entities":
        k = f" ({args.get('kind')})" if args.get("kind") else ""
        return f"Verifică entitățile stratului „{args.get('layer')}”{k}"
    if name == "search_texts":
        return f"Caută textul „{args.get('query')}” pe planșă"
    if name == "entities_near":
        return f"Verifică ce se află lângă punctul ({args.get('x')}, {args.get('y')})"
    return f"{name}({args})"
