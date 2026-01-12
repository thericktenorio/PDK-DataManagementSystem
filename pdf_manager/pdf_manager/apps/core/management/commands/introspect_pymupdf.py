from __future__ import annotations

from pathlib import Path

import fitz  # PyMuPDF
from django.core.management.base import BaseCommand, CommandError


def _truncate(s: str, limit: int = 2000) -> str:
    """Truncate long strings for console output."""
    if len(s) <= limit:
        return s
    return s[:limit] + f"\n... [truncated, total length={len(s)} chars]"


def _header(title: str) -> None:
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)


def inspect_page(doc: fitz.Document, page_index: int) -> None:
    """Print detailed PyMuPDF introspection for a single page."""
    page = doc[page_index]
    _header(f"PAGE {page_index}")

    # ------------------------------------------------------------------
    # 1) get_text("text")
    # ------------------------------------------------------------------
    print("\n--- get_text('text') ---")
    try:
        text = page.get_text("text") or ""
        print(_truncate(text) or "<EMPTY>")
    except Exception as exc:
        print(f"<ERROR: {exc!r}>")

    # ------------------------------------------------------------------
    # 2) get_text("dict") blocks/lines/spans
    # ------------------------------------------------------------------
    print("\n--- get_text('dict') blocks/lines/spans ---")
    try:
        data = page.get_text("dict")
        blocks = data.get("blocks", [])
        if not blocks:
            print("<NO BLOCKS>")
        else:
            for bi, block in enumerate(blocks):
                btype = block.get("type")
                bbox = block.get("bbox")
                print(f"\nBlock #{bi}: type={btype}, bbox={bbox}")
                for li, line in enumerate(block.get("lines", [])):
                    print(f"  Line #{li}:")
                    for si, span in enumerate(line.get("spans", [])):
                        font = span.get("font")
                        size = span.get("size")
                        span_text = span.get("text", "")
                        print(
                            f"    Span #{si}: font={font}, size={size}, "
                            f"text={_truncate(repr(span_text), 200)}"
                        )
    except Exception as exc:
        print(f"<ERROR: {exc!r}>")

    # ------------------------------------------------------------------
    # 3) get_text("raw")
    # ------------------------------------------------------------------
    print("\n--- get_text('raw') ---")
    try:
        raw = page.get_text("raw") or ""
        print(_truncate(raw))
    except Exception as exc:
        print(f"<ERROR: {exc!r}>")

    # ------------------------------------------------------------------
    # 4) Images
    # ------------------------------------------------------------------
    print("\n--- page.get_images(full=True) ---")
    try:
        images = page.get_images(full=True)
        if not images:
            print("<NO IMAGES>")
        else:
            print(f"Total images: {len(images)}")
            for idx, img in enumerate(images):
                xref = img[0]
                width, height = img[2], img[3]
                colorspace = img[4]
                bpc = img[5]
                print(
                    f"  Image #{idx}: xref={xref}, {width}x{height}, " f"cs={colorspace}, bpc={bpc}"
                )
    except Exception as exc:
        print(f"<ERROR: {exc!r}>")

    # ------------------------------------------------------------------
    # 5) Fonts (when available)
    # ------------------------------------------------------------------
    print("\n--- Fonts (page.get_fonts) ---")
    try:
        if hasattr(page, "get_fonts"):
            fonts = page.get_fonts()
            if not fonts:
                print("<NO FONTS REPORTED>")
            else:
                print(f"Total fonts: {len(fonts)}")
                for fi, font in enumerate(fonts):
                    # Structure varies by version; just print raw tuple
                    print(f"  Font #{fi}: {font}")
        else:
            print("<page.get_fonts not supported>")
    except Exception as exc:
        print(f"<ERROR: {exc!r}>")


class Command(BaseCommand):
    """
    Deep PyMuPDF inspection of specific PDF pages (Phase 7 debugging).

    Usage:

      # Inspect all pages
      python manage.py introspect_pymupdf --input /path/to/file.pdf

      # Inspect selected pages (0-based indices)
      python manage.py introspect_pymupdf --input /path/to/file.pdf --pages 35 36 38 39
    """

    help = "Deep PyMuPDF inspection of specific PDF pages (Phase 7 debugging)."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--input",
            "-i",
            type=str,
            required=True,
            help="Path to PDF file.",
        )
        parser.add_argument(
            "--pages",
            "-p",
            type=int,
            nargs="*",
            required=False,
            help=(
                "0-based page indices to inspect (e.g. --pages 35 36 38 39). "
                "If omitted, all pages will be inspected."
            ),
        )

    def handle(self, *args, **opts) -> None:
        pdf_path = Path(opts["input"]).expanduser()
        if not pdf_path.exists():
            raise CommandError(f"PDF does not exist: {pdf_path}")

        print(f"Opening PDF: {pdf_path}")
        try:
            doc = fitz.open(pdf_path.as_posix())
        except Exception as exc:
            raise CommandError(f"Failed to open PDF with PyMuPDF: {exc!r}") from exc

        try:
            count = doc.page_count
            print(f"Total pages: {count}")

            pages = opts.get("pages") or []
            if not pages:
                # Default: inspect all pages
                pages = list(range(count))

            for idx in pages:
                if idx < 0 or idx >= count:
                    self.stderr.write(f"[WARN] Skipping invalid page index: {idx}")
                    continue
                inspect_page(doc, idx)
        finally:
            doc.close()
