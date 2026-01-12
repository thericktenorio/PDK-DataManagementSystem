from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from django.core.management.base import BaseCommand, CommandError

from pdf_manager.apps.parser.events import EventBus
from pdf_manager.apps.parser.facade import PDFParserFacade
from pdf_manager.apps.parser.observers.audit_observer import AuditObserver


class Command(BaseCommand):
    help = "Run the PDF parsing pipeline on a local file path"

    def add_arguments(self, parser):
        parser.add_argument("file_path", nargs="?", help="Path to a PDF file")
        parser.add_argument(
            "--input", dest="input", help="Path to a PDF file (preferred over positional argument)"
        )
        parser.add_argument(
            "--template",
            dest="template",
            default=None,
            help="Optional template key (e.g., 'w2', '1099')",
        )

    def handle(self, *args, **options):
        # Resolve input path from --input or positional file_path
        input_path = options.get("input") or options.get("file_path")
        if not input_path:
            raise CommandError("You must provide a path (use --input or positional file_path).")

        p = Path(input_path).expanduser().resolve()
        if not p.exists() or not p.is_file():
            raise CommandError(f"File not found: {p}")

        template_key = options.get("template")

        bus = EventBus()
        bus.subscribe(AuditObserver())  # console audit for Phase 2

        facade = PDFParserFacade(event_bus=bus)

        # Prefer full pipeline (ingestion + parse) if available:
        if hasattr(facade, "run"):
            result = facade.run(input_path=str(p), template_key=template_key)
        else:
            # Fallback to existing direct-parse behavior (no ingestion)
            result = facade.parse(job_id=uuid4(), file_path=str(p))

        self.stdout.write(self.style.SUCCESS(result.message))
        self.stdout.write(f"Subset: {result.output_subset_path}")
