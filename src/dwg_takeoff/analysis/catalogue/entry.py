"""A catalogue entry: one group of entities the engine can select exactly, measured and named."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

PREFIX = {"surface": "S", "outline": "O", "linear": "L", "block": "B", "nested_block": "N", "table": "T", "part": ""}
MEASURE = {
    "surface": "area",
    "outline": "area",
    "linear": "length",
    "block": "count",
    "nested_block": "count",
    "table": "area",
    "part": "area",
}


@dataclass
class Entry:
    id: str
    key: str  # stable identity: labels are stored under it
    kind: str  # surface | outline | linear | block | nested_block | table
    layer: str | None
    filters: list[dict]  # engine sources selecting exactly this entry
    measure: str  # usual measure: area | length | count
    n: int = 0  # entities (whole drawing)
    n_site: int | None = None  # entities inside the site region (None: no site region)
    area: float | None = None  # m² (union) in the site region, or whole drawing without one
    area_all: float | None = None
    length: float | None = None  # m, raw drawn length (site)
    length_dedup: float | None = None  # m, coincident traces merged (site)
    count: int | None = None
    pattern: str | None = None
    color: str | None = None
    color_name: str | None = None
    block: str | None = None
    in_block: str | None = None  # content of a container block: its name
    size_m: float | None = None  # blocks: median size of the drawn symbol (largest side)
    width_m: float | None = None  # wide polylines: drawn stripe width
    visible: bool = True
    legend: list[str] = field(default_factory=list)
    callouts: list[str] = field(default_factory=list)
    texts: list[str] = field(default_factory=list)  # written inside (rooms, zones)
    dims: list[str] = field(default_factory=list)  # dimension values written on it
    attributes: dict = field(default_factory=dict)  # block attribute tag -> sample values
    descriptions: list[str] = field(default_factory=list)  # layer / block descriptions
    duplicates: list[dict] = field(default_factory=list)  # {"key", "id", "relation", "overlap_m2"}
    edges: list[dict] = field(default_factory=list)  # surfaces: line entries their boundary runs along
    edge_of: list[dict] = field(default_factory=list)  # lines: surfaces they edge
    vocab: list[dict] = field(default_factory=list)  # {"category", "score", "evidence"}
    auto_label: str = ""
    auto_label_source: str = ""  # legend | callout | text
    parent: str | None = None  # parts: key of the entry they belong to
    split_color: bool = False  # one of several colours of the same layer / block

    def to_dict(self) -> dict:
        return asdict(self)


def group_key(gk) -> str:
    """Stable key of a feature group: its kind, layer, pattern, colour, block and container."""
    return "|".join(x or "" for x in gk)


def sort_key(e) -> tuple:
    """Catalogue order: by kind, then number; parts right after their entry."""
    eid = e.id if isinstance(e, Entry) else e["id"]
    head, _, sub = eid.partition(".")
    kind = {v: k for k, v in PREFIX.items() if v}.get(head[0], "part")
    return (list(PREFIX).index(kind), int(head[1:]), int(sub or 0))
