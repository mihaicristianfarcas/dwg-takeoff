"""Reading CAD drawings: DWG -> DXF conversion, then a measurable `Drawing` (shapely geometry for
every entity, layers, legends, sheets, tables, units)."""

from .entities import load_doc
from .extract import apply_units, extract
from .model import Drawing, EmbeddedTable, Feature, LayerInfo, LegendEntry

__all__ = ["Drawing", "EmbeddedTable", "Feature", "LayerInfo", "LegendEntry", "apply_units", "extract", "load_doc"]
