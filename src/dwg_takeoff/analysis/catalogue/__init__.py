"""The element catalogue: every measurable group of entities of a drawing, numbered, measured and named.

This is the deterministic step between extraction and the AI. Each entry is exactly what one
engine filter selects (a layer's fills of one pattern and colour, a layer's lines, a block type,
a table footprint...), so choosing an entry *is* choosing a source. For every entry the catalogue
states what can be checked without judgement:

  * how many entities, how much area / length / how many items, inside and outside the site region
  * the legend label drawn for it, callouts pointing at it, texts written inside it, dimensions on it
  * the entries that draw the same surface again (fill + outline, frozen copies)
  * block sizes and attribute values, layer / block descriptions, hidden layers
  * what the English vocabulary says it is (category, how it is usually measured, evidence)
  * the label: the user's (editable, stored by a stable key), else the legend's / a callout's

Blocks are countable symbols; only the content of *container* blocks (a survey, a playground or a
whole plan placed as one block) is broken down into entries of its own.

The AI answers by picking entry ids; the planner turns them back into filters, so stored plans
keep working when the catalogue is rebuilt.
"""

from .build import build_catalogue
from .entry import Entry, sort_key
from .expand import entry_index, expand_entries
from .labels import Labels, with_labels
from .text import catalogue_text, entry_line, write_csv

__all__ = [
    "Entry",
    "Labels",
    "build_catalogue",
    "catalogue_text",
    "entry_index",
    "entry_line",
    "expand_entries",
    "sort_key",
    "with_labels",
    "write_csv",
]
