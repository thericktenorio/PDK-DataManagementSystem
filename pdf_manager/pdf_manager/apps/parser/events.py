from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .types import ParseJob


@dataclass(frozen=True)
class IngestionCompleted:
    job: ParseJob


@dataclass(frozen=True)
class Event:
    name: str
    payload: dict[str, Any]


class Observer(Protocol):
    def on_event(self, event: Event) -> None: ...


class EventBus:
    def __init__(self) -> None:
        self._subs: list[Observer] = []

    def subscribe(self, obs: Observer) -> None:
        self._subs.append(obs)

    def publish(self, event: Event) -> None:
        for s in list(self._subs):
            s.on_event(event)


# Event names (constants)
EVT_INPUT_VALIDATED = "input_validated"
EVT_PAGES_TAGGED = "pages_tagged"
EVT_FIELDS_EXTRACTED = "fields_extracted"
EVT_SUBSET_WRITTEN = "subset_written"
EVT_MESSAGE_GENERATED = "message_generated"
EVT_INGESTION_COMPLETED = "ingestion.completed"
EVT_INGESTION_FAILED = "ingestion.failed"
