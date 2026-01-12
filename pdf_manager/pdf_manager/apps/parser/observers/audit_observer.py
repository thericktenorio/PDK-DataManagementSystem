from __future__ import annotations

from pdf_manager.apps.parser.events import Event, Observer


class AuditObserver(Observer):
    def __init__(self) -> None:
        # Phase 2: just print/log; Phase 3: write AuditEvent rows
        pass

    def on_event(self, event: Event) -> None:
        # replace with proper logging in Phase 3
        print(f"[AUDIT] {event.name} :: {event.payload}")
