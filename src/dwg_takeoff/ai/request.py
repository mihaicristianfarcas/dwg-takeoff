"""One planning request: the drawing, its digest, the client's question, progress events and
cancellation. Backends receive a `PlanRequest` and report through `PlanRequest.say`."""

from __future__ import annotations

import contextlib
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ..cad.model import Drawing


class PlannerError(RuntimeError):
    pass


class Cancelled(PlannerError):
    pass


@dataclass
class PlanEvent:
    kind: str  # stage | done | thought | lookup | lookup_done | usage | warning
    text: str
    id: str | None = None
    detail: str | None = None
    t: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v is not None}


EventSink = Callable[[PlanEvent], None]


class CancelToken:
    def __init__(self):
        self._ev = threading.Event()
        self.on_cancel: list[Callable[[], None]] = []

    def cancel(self) -> None:
        self._ev.set()
        for cb in list(self.on_cancel):
            with contextlib.suppress(Exception):
                cb()

    @property
    def cancelled(self) -> bool:
        return self._ev.is_set()

    def check(self) -> None:
        if self.cancelled:
            raise Cancelled("Analiza a fost anulată.")


@dataclass
class PlanRequest:
    query: str
    drawing: Drawing
    digest: dict
    digest_text: str
    region: object  # shapely polygon of the site region or None
    table_transform: object
    run_dir: Path
    effort: str = "medium"
    model: str | None = None
    emit: EventSink = lambda e: None
    cancel: CancelToken = field(default_factory=CancelToken)
    project_info: str = ""  # notes, client answers, reference documents (text)
    labels: dict = field(default_factory=dict)  # the user's labels of catalogue entries

    def request_text(self) -> str:
        """The user turn: project information (if any) and the client's request."""
        info = (
            (
                f"=== PROJECT INFORMATION (notes, client answers, reference documents; read, never measured) ===\n"
                f"{self.project_info.strip()}\n\n"
            )
            if self.project_info.strip()
            else ""
        )
        return info + "=== CLIENT REQUEST ===\n" + self.query.strip()

    def say(self, kind: str, text: str, **kw) -> None:
        self.emit(PlanEvent(kind, text, **kw))
