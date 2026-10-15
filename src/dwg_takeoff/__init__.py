"""DWG Takeoff: quantity takeoff from CAD drawings, with every number traceable to the entities
it was measured on.

Pipeline: `cad` reads a DWG/DXF into a `Drawing`; `analysis` builds the element catalogue and the
digest; `ai` turns a request into a takeoff plan; `engine` measures the plan; `web` and `cli` are
the two front ends. See docs/architecture.md.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("dwg-takeoff")
except PackageNotFoundError:  # running from a source tree that was not installed
    __version__ = "0.0.0"


def main() -> None:
    from .cli import main as _main

    _main()
