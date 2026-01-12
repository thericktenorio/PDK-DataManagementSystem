from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from pdf_manager.apps.parser.introspection import PageIntrospection, introspect_local_file


class Command(BaseCommand):
    help = "Phase 7.0: Ingest a PDF and print per-page introspeciton info."

    def add_arguments(self, parser):
        parser.add_argument("file_path", nargs="?", help="Path to a PDF file")
        parser.add_argument(
            "--input",
            dest="input",
            help="Path to a PDF file (preferred over positional argument)",
        )
        parser.add_argument(
            "--format",
            dest="format",
            choices=["text", "json"],
            default="text",
            help="Output format (default: text)",
        )

    def handle(self, *args, **options):
        # Resolve input path from --input or positional file_path
        input_path = options.get("input") or options.get("file_path")
        if not input_path:
            raise CommandError("You must provide a path (use --input or positional file_path).")

        p = Path(input_path).expanduser().resolve()
        if not p.exists() or not p.is_file():
            raise CommandError(f"File not found: {p}")

        fmt = options.get("format", "text")

        job_id, stored_path, pages = introspect_local_file(p)

        if fmt == "json":
            self._print_json(job_id, stored_path, pages)
        else:
            self._print_text(job_id, stored_path, pages)

    # ---- helpers --------------------
    def _print_text(
        self,
        job_id: str,
        stored_path: Path,
        pages: list[PageIntrospection],
    ) -> None:
        self.stdout.write(self.style.NOTICE(f"Job ID: {job_id}"))
        self.stdout.write(self.style.NOTICE(f"Stored path: {stored_path}"))
        self.stdout.write(self.style.NOTICE(f"Total pages: {len(pages)}"))
        self.stdout.write("")

        for pi in pages:
            tags_str = ", ".join(t.label for t in pi.tags) if pi.tags else "(none)"
            outlines_str = "; ".join(pi.outline_titles) if pi.outline_titles else "(none)"

            self.stdout.write("-" * 80)
            self.stdout.write(f"Page {pi.index}")
            self.stdout.write(f".   Tags: {tags_str}")
            self.stdout.write(f".   Outlines: {outlines_str}")
            self.stdout.write(".   Text preview:")
            self.stdout.write(f".   {pi.text_preview}")
        self.stdout.write("-" * 80)

    def _print_json(
        self,
        job_id: str,
        stored_path: Path,
        pages: list[PageIntrospection],
    ) -> None:
        def tag_to_dict(tag):
            return {"label": tag.label, "score": tag.score, "meta": tag.meta or {}}

        payload = {
            "job_id": job_id,
            "stored_path": str(stored_path),
            "pages": [
                {
                    "index": pi.index,
                    "tags": [tag_to_dict(t) for t in pi.tags],
                    "outline_titles": pi.outline_titles,
                    "text_preview": pi.text_preview,
                }
                for pi in pages
            ],
        }
        self.stdout.write(json.dumps(payload, indent=2))
