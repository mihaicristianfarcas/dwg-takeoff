"""Deterministic vocabulary: what a layer / block / legend label / callout most likely names.

English only for now (the structure takes other languages as more term lists). Every category says
how it is usually measured, so a catalogue entry can be pre-classified before any AI sees it:

    classify([("layer", "C-ROAD-CURB"), ("legend", "Concrete curb 20x25")])
    -> [Match(category="curb", score=..., evidence=[...])]

Matching is on normalised tokens (lower case, camelCase and digits split, simple plurals) and on
CAD layer-naming standards (US National CAD Standard / AIA: discipline letter + major group, e.g.
A-WALL, C-ROAD, L-PLNT, with minor groups such as -CURB or -TREE).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# id -> (name, how it is measured, terms). Terms are words or short phrases; matching is on whole
# (normalised) words, so "bed" matches "flower bed" but not "embedded".
CATEGORIES: dict[str, tuple[str, str, list[str]]] = {
    "building": (
        "Building / footprint",
        "area",
        [
            "building",
            "bldg",
            "house",
            "footprint",
            "structure",
            "outbuilding",
            "garage",
            "shed",
            "pavilion",
            "kiosk",
            "canopy",
            "construction",
        ],
    ),
    "wall": ("Wall", "length", ["wall", "partition", "masonry", "brickwork", "retaining wall", "parapet"]),
    "door": ("Door", "count", ["door", "doorway", "gate", "dr"]),
    "window": ("Window", "count", ["window", "glazing", "glaz", "curtain wall", "skylight"]),
    "stair": ("Stair", "count", ["stair", "staircase", "stairwell", "stairway", "steps", "strs"]),
    "elevator": ("Elevator / lift", "count", ["elevator", "lift", "elev"]),
    "room": (
        "Room / space",
        "area",
        [
            "room",
            "bedroom",
            "kitchen",
            "living",
            "dining",
            "bathroom",
            "bath",
            "toilet",
            "wc",
            "corridor",
            "hall",
            "hallway",
            "lobby",
            "office",
            "storage",
            "closet",
            "garage space",
            "laundry",
            "utility room",
        ],
    ),
    "road": (
        "Road / driveway",
        "area",
        [
            "road",
            "roadway",
            "carriageway",
            "street",
            "drive",
            "driveway",
            "drive through",
            "drivethru",
            "lane",
            "asphalt",
            "tarmac",
            "bitumen",
            "pavement structure",
        ],
    ),
    "parking": ("Parking", "area", ["parking", "car park", "carpark", "parking lot", "parking bay", "stall", "pkng"]),
    "paving": (
        "Paving (pavers, slabs, footpaths)",
        "area",
        [
            "paving",
            "paver",
            "pavers",
            "paved",
            "pavement",
            "sidewalk",
            "footpath",
            "footway",
            "walkway",
            "path",
            "pathway",
            "plaza",
            "promenade",
            "terrace",
            "patio",
            "tile",
            "tiles",
            "cobble",
            "cobblestone",
            "sett",
            "block paving",
            "flagstone",
            "flag",
            "pedestrian",
        ],
    ),
    "curb": (
        "Curb / kerb / edging",
        "length",
        ["curb", "kerb", "curbstone", "kerbstone", "edging", "edge restraint", "gutter"],
    ),
    "concrete": (
        "Concrete (slab, footing, base)",
        "area",
        ["concrete", "slab", "footing", "foundation", "pad", "base course", "screed", "fdn"],
    ),
    "lawn": ("Lawn / grass", "area", ["lawn", "grass", "turf", "sod", "seeding", "green area", "greenery", "meadow"]),
    "planting": (
        "Planting bed",
        "area",
        [
            "planting",
            "plant bed",
            "flower bed",
            "flowerbed",
            "bed",
            "groundcover",
            "ground cover",
            "perennial",
            "perennials",
            "flowers",
            "plnt",
        ],
    ),
    "tree": (
        "Tree",
        "count",
        [
            "tree",
            "conifer",
            "coniferous",
            "deciduous",
            "evergreen",
            "pine",
            "spruce",
            "abies",
            "thuja",
            "thuya",
            "cedar",
            "larch",
            "oak",
            "maple",
            "birch",
            "linden",
            "lime tree",
            "ash",
            "beech",
            "poplar",
            "willow",
            "elm",
            "chestnut",
            "rowan",
            "palm",
            "cypress",
            "juniper tree",
            "acer",
            "quercus",
            "betula",
            "pinus",
            "picea",
            "canopy tree",
        ],
    ),
    "shrub": ("Shrub / hedge", "count", ["shrub", "shrubs", "bush", "hedge", "hedging", "boxwood", "juniper"]),
    "fence": (
        "Fence / railing",
        "length",
        ["fence", "fencing", "railing", "balustrade", "palisade", "barrier", "guardrail", "fenc"],
    ),
    "gravel": (
        "Gravel / loose stone",
        "area",
        ["gravel", "crushed stone", "aggregate", "pebble", "pebbles", "shingle", "chippings", "ballast"],
    ),
    "wood": ("Wood / decking", "area", ["deck", "decking", "timber", "wood", "wooden", "boardwalk", "planks"]),
    "stone": ("Stone", "area", ["stone", "granite", "basalt", "limestone", "natural stone", "boulder"]),
    "water": ("Water / pool", "area", ["pond", "pool", "water", "fountain", "basin", "lake", "stream"]),
    "play": (
        "Play / sports area",
        "area",
        [
            "playground",
            "play area",
            "play",
            "sport",
            "sports",
            "court",
            "pitch",
            "field",
            "track",
            "rubber",
            "safety surface",
        ],
    ),
    "marking": (
        "Road marking",
        "length",
        ["marking", "markings", "stripe", "striping", "strp", "line marking", "crosswalk", "zebra", "arrow"],
    ),
    "furniture": (
        "Site furniture / equipment",
        "count",
        [
            "bench",
            "bin",
            "litter bin",
            "lamp",
            "light",
            "lighting",
            "luminaire",
            "pole",
            "post",
            "bollard",
            "sign",
            "signage",
            "bike rack",
            "bicycle",
            "table",
            "seat",
            "planter",
        ],
    ),
    "vehicle": ("Vehicle", "count", ["car", "vehicle", "truck", "bus", "auto"]),
    "drainage": (
        "Drainage / sewer",
        "length",
        [
            "drain",
            "drainage",
            "sewer",
            "storm",
            "stormwater",
            "sanitary",
            "manhole",
            "gully",
            "culvert",
            "swale",
            "pipe",
            "stm",
            "sswr",
        ],
    ),
    "utility": (
        "Utility line",
        "length",
        [
            "water main",
            "water line",
            "gas",
            "electric",
            "electrical",
            "power",
            "cable",
            "telecom",
            "fiber",
            "fibre",
            "duct",
            "conduit",
            "irrigation",
            "watr",
            "elec",
            "comm",
        ],
    ),
    "boundary": (
        "Property / site boundary",
        "length",
        [
            "property",
            "property line",
            "boundary",
            "lot",
            "plot",
            "parcel",
            "setback",
            "easement",
            "limit",
            "site boundary",
            "prop",
        ],
    ),
    "topography": (
        "Topography / levels",
        "none",
        ["contour", "contours", "elevation", "spot level", "level", "topo", "survey", "grade", "grading"],
    ),
    "annotation": (
        "Annotation (not measured)",
        "none",
        [
            "text",
            "txt",
            "anno",
            "annotation",
            "dim",
            "dims",
            "dimension",
            "note",
            "notes",
            "title",
            "border",
            "frame",
            "viewport",
            "vport",
            "defpoints",
            "legend",
            "label",
            "tag",
            "symbol",
            "hatch pattern",
            "grid",
            "axis",
            "axes",
            "north",
            "scale bar",
            "revision",
            "logo",
        ],
    ),
}

# National CAD Standard (AIA) major / minor groups -> category (discipline letter is ignored).
NCS_GROUPS: dict[str, str] = {
    "WALL": "wall",
    "DOOR": "door",
    "GLAZ": "window",
    "WIND": "window",
    "STRS": "stair",
    "ELEV": "elevator",
    "ROAD": "road",
    "PKNG": "parking",
    "PAVE": "paving",
    "WALK": "paving",
    "SDWK": "paving",
    "CURB": "curb",
    "CONC": "concrete",
    "FNDN": "concrete",
    "SLAB": "concrete",
    "PLNT": "planting",
    "TREE": "tree",
    "SHRB": "shrub",
    "TURF": "lawn",
    "LAWN": "lawn",
    "FENC": "fence",
    "STRP": "marking",
    "STRM": "drainage",
    "SSWR": "drainage",
    "DRAN": "drainage",
    "WATR": "utility",
    "NGAS": "utility",
    "POWR": "utility",
    "ELEC": "utility",
    "COMM": "utility",
    "PROP": "boundary",
    "BNDY": "boundary",
    "ESMT": "boundary",
    "TOPO": "topography",
    "CNTR": "topography",
    "BLDG": "building",
    "STRC": "building",
    "FURN": "furniture",
    "SITE": None,
    "ANNO": "annotation",
    "DIMS": "annotation",
    "TEXT": "annotation",
    "SYMB": "annotation",
    "IDEN": "annotation",
    "NPLT": "annotation",
    "GRID": "annotation",
    "ROOF": "building",
    "FLOR": "room",
    "AREA": "room",
}

# how much a word found in each kind of source says about the entry
SOURCE_WEIGHT = {
    "user": 10.0,
    "legend": 4.0,
    "callout": 3.5,
    "layer_description": 3.0,
    "block_description": 3.0,
    "layer": 2.5,
    "block": 2.5,
    "attribute": 2.0,
    "inside_text": 1.5,
}


@dataclass
class Match:
    category: str
    score: float
    evidence: list[str] = field(default_factory=list)  # "layer 'C-ROAD-CURB' (curb)"

    @property
    def name(self) -> str:
        return CATEGORIES[self.category][0]

    @property
    def measure(self) -> str:
        return CATEGORIES[self.category][1]


_CAMEL = re.compile(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z])")
_NCS = re.compile(r"^[A-Z]-([A-Z]{4})(?:-([A-Z]{4}))?(?:-([A-Z]{4}))?(?:$|-)")


def _stem(w: str) -> str:
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 4 and w.endswith(("ches", "shes", "sses", "xes")):
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def tokens(text: str) -> list[str]:
    """Normalised words of a layer name, label or text ("TreesNew_2" -> ["tree", "new", "2"])."""
    text = _CAMEL.sub(" ", text or "")
    return [_stem(w) for w in re.split(r"[^a-z0-9]+", text.lower()) if w]


def _index() -> tuple[dict[str, list[tuple[tuple[str, ...], str]]], int]:
    idx: dict[str, list[tuple[tuple[str, ...], str]]] = {}
    longest = 1
    for cat, (_, _, terms) in CATEGORIES.items():
        for term in terms:
            tk = tuple(tokens(term))
            if tk:
                idx.setdefault(tk[0], []).append((tk, cat))
                longest = max(longest, len(tk))
    for lst in idx.values():
        lst.sort(key=lambda x: -len(x[0]))  # longest phrase first ("retaining wall" before "wall")
    return idx, longest


_IDX, _LONGEST = _index()


def term_hits(text: str) -> list[tuple[str, str]]:
    """(category, matched term) for every vocabulary term in `text`, in reading order."""
    out = []
    m = _NCS.match((text or "").strip())
    if m:  # standard layer name: major group, then the more specific minor groups
        for grp in m.groups():
            cat = NCS_GROUPS.get(grp or "")
            if cat:
                out.append((cat, grp))
        return out
    tk = tokens(text)
    i = 0
    while i < len(tk):
        hit = None
        for phrase, cat in _IDX.get(tk[i], []):
            if tuple(tk[i : i + len(phrase)]) == phrase:
                hit = (phrase, cat)
                break
        if hit:
            out.append((hit[1], " ".join(hit[0])))
            i += len(hit[0])
        else:
            i += 1
    return out


def classify(sources: list[tuple[str, str]], top: int = 3) -> list[Match]:
    """Rank categories for an entry from its (source kind, text) pairs, best first. The source kind
    sets the weight; within one text the last term is the head noun ("concrete curb" is a curb,
    "C-ROAD-CURB" too), earlier terms count half."""
    scores: dict[str, Match] = {}
    for kind, text in sources:
        if not text:
            continue
        w = SOURCE_WEIGHT.get(kind, 1.0)
        hits = term_hits(text)
        best: dict[str, tuple[float, str]] = {}
        for i, (cat, term) in enumerate(hits):
            f = 1.0 if i == len(hits) - 1 else 0.5
            if f > best.get(cat, (0.0, ""))[0]:
                best[cat] = (f, term)
        for cat, (f, term) in best.items():
            m = scores.setdefault(cat, Match(cat, 0.0))
            m.score += w * f
            if len(m.evidence) < 4:
                m.evidence.append(f"{kind.replace('_', ' ')} '{text[:60]}' ({term})")
    ranked = sorted(scores.values(), key=lambda m: -m.score)
    return ranked[:top]


def category_choices() -> list[dict]:
    return [{"id": k, "name": v[0], "measure": v[1]} for k, v in CATEGORIES.items()]
