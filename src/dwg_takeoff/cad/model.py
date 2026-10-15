"""The measurable model of a drawing, produced by `extract` and used by everything downstream.

* ``Drawing.features`` - every model-space entity as shapely geometry. Blocks are exploded; nested
  entities keep the handle of the top-level INSERT, so they can be found in AutoCAD.
* ``Drawing.layers`` - the layer table with on / off / frozen state, colour and description.
* ``Drawing.legends`` - legend entries (a hatch swatch, a line sample or a symbol, and its label).
* ``Drawing.tables`` / ``text_tables`` - embedded tables (Excel / Word, AutoCAD tables) and tables
  drawn as aligned texts (room schedules, land-use balances, setting-out coordinates).
* ``Drawing.layouts`` - sheets with their titles and viewports (model window, scale, frozen layers).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from shapely.geometry.base import BaseGeometry


@dataclass
class Feature:
    fid: int
    handle: str  # handle of the top-level entity (for nested geometry: the INSERT)
    layer: str
    dxftype: str
    kind: str  # hatch | solid | closed | line | block | text
    geom: BaseGeometry
    pattern: str | None = None
    block: str | None = None  # INSERT: block name; nested geometry: containing block name
    nested: bool = False
    text: str | None = None
    text_height: float | None = None
    visible: bool = True  # layer on and not frozen (for nested: parent INSERT layer too)
    width: float | None = None  # constant polyline width (drawn stripe width), if any
    color: str | None = None  # effective display colour "#rrggbb" (BYLAYER/BYBLOCK resolved)
    aci: int | None = None  # AutoCAD colour index when the colour is not a true colour
    attribs: dict | None = None  # INSERT: attribute tag -> value

    @property
    def area(self) -> float:
        return self.geom.area if self.kind in ("hatch", "solid", "closed") else 0.0

    @property
    def length(self) -> float:
        if self.kind in ("hatch", "solid", "closed"):
            return self.geom.boundary.length
        if self.kind == "line":
            return self.geom.length
        return 0.0


@dataclass
class LayerInfo:
    name: str
    color: tuple[int, int, int]
    on: bool
    frozen: bool
    locked: bool
    linetype: str
    aci: int | None = None
    description: str = ""  # the layer's description in the drawing (layer manager)

    @property
    def visible(self) -> bool:
        return self.on and not self.frozen


@dataclass
class Callout:
    """A leader or multileader: a text with an arrow pointing at the thing it names."""

    text: str | None  # None: no text attached to the leader (the nearest text is used)
    tip: tuple[float, float]  # arrow head, on the named thing
    end: tuple[float, float]  # where the text sits
    layer: str
    handle: str


@dataclass
class DimensionNote:
    """A dimension: what it measures (drawing units) and where it is."""

    kind: str  # linear | aligned | radius | diameter | angular
    value: float
    text: str  # the displayed text when the designer overrode the measurement, else ""
    at: tuple[float, float]
    layer: str
    handle: str


@dataclass
class LegendEntry:
    layout: str
    label: str
    sample: str  # hatch | line | block
    layer: str
    pattern: str | None
    block: str | None
    color: str | None  # "#rrggbb" of the swatch
    handle: str | None = None  # model-space legends: the swatch entity (a sample, never measured)


@dataclass
class ViewportInfo:
    layout: str
    handle: str
    model_center: tuple[float, float]
    view_height: float
    view_width: float
    twist_deg: float
    scale: float  # paper units per model unit
    frozen_layers: list[str]
    denominator: float | None = None  # true plot scale 1:N (paper and model units accounted for)


@dataclass
class LayoutInfo:
    name: str
    titles: list[str]
    viewports: list[ViewportInfo]
    notes: list[str]


@dataclass
class EmbeddedTable:
    tid: str
    layouts: list[str]
    kind: str  # xlsx | docx
    title: str
    rows: list[list]
    objects: dict[str, list[tuple[str, float, float]]] = field(default_factory=dict)


@dataclass
class Drawing:
    source_name: str
    dxf_path: str
    dxf_version: str
    units: str
    unit_scale: float  # drawing unit -> meters
    layers: dict[str, LayerInfo]
    features: list[Feature]
    legends: list[LegendEntry]
    layouts: list[LayoutInfo]
    tables: list[EmbeddedTable]
    xrefs: list[str]
    warnings: list[str]
    space: str = "Model"  # layout the measured geometry comes from
    unit_info: dict = field(default_factory=dict)
    text_tables: list = field(default_factory=list)  # tables drawn as aligned texts
    callouts: list = field(default_factory=list)  # Callout, in the measured space (also inside blocks)
    dimensions: list = field(default_factory=list)  # DimensionNote, in the measured space
    block_descriptions: dict = field(default_factory=dict)  # block name -> description
    legend_handles: set = field(default_factory=set)  # model-space legend swatches: samples, never measured

    def by_layer(self) -> dict[str, list[Feature]]:
        out: dict[str, list[Feature]] = {}
        for f in self.features:
            out.setdefault(f.layer, []).append(f)
        return out

    def feature(self, fid: int) -> Feature:
        return self.features[fid]
