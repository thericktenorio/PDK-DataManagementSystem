# minimal concrete placeholder so the pipeline can run
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from PyPDF2 import PdfReader, PdfWriter  # installed already via requirements.txt
from PyPDF2.errors import PdfReadError
from PyPDF2.generic import Destination

from pdf_manager.apps.parser.adapters.pdf_reader_base import PdfReaderAdapter
from pdf_manager.apps.parser.types import OutlineInfo, PdfPage


class PyPDF2Reader(PdfReaderAdapter):
    def __init__(self, file_path: Path) -> None:
        super().__init__(file_path)
        self.file_path = file_path
        try:
            self.reader = PdfReader(str(file_path))
            if getattr(self.reader, "is_encrypted", False):
                # MVP: try empty password; otherwise fail friendly
                try:
                    self.reader.decrypt("")
                except Exception as e:
                    raise PdfReadError(f"Encrypted PDF not supported in MVP: {file_path}") from e
        except Exception as e:
            raise PdfReadError(f"Failed to open PDF: {file_path}") from e

    def pages(self) -> list[PdfPage]:
        # Build outline mapping once: page_index -> [outline titles]
        outlines_map = self.outlines_by_page()  # dict[int, list[str]]

        pages: list[PdfPage] = []
        num_pages = len(self.reader.pages)

        for i in range(num_pages):
            raw_page = self.reader.pages[i]
            titles = outlines_map.get(i) or []
            outline_info: OutlineInfo | None = None

            if titles:
                title = str(titles[0])
                section_key = self._normalize_section_key(title)
                outline_info = OutlineInfo(
                    title=title,
                    path=(title,),  # simple 1 step path for now; can be expanded later
                    section_key=section_key,
                )

            pages.append(
                PdfPage(
                    index=i,
                    raw=raw_page,
                    outline=outline_info,
                    source_path=self.file_path,
                )
            )

        return pages

    def extract_text(self, page_idx: int) -> str:
        try:
            text = self.reader.pages[page_idx].extract_text()
            return text or ""
        except Exception:
            return ""

    def write_subset(self, page_order: Sequence[int], out_path: Path) -> Path:
        writer = PdfWriter()
        for i in page_order:
            writer.add_page(self.reader.pages[i])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("wb") as f:
            writer.write(f)
        return out_path

    def outlines_by_page(self) -> dict[int, list[str]]:
        """
        Return a mapping of page_index -> [outline titles] for that page.
        This is used for Phase 7.0 introspection only. If the PDF has no
        outlines/bookmarks, then this will return an empty string.
        """
        outlines_map: dict[int, list[str]] = {}

        # some PyPDF2 versions expose .outline, others .outlines
        try:
            outlines = getattr(self.reader, "outline", None) or getattr(
                self.reader, "outlines", None
            )
        except Exception:
            outlines = None

        if not outlines:
            return outlines_map

        def walk(tree):
            for item in tree:
                if isinstance(item, Destination):
                    try:
                        page_index = self.reader.get_destination_page_number(item)
                    except Exception:
                        continue
                    outlines_map.setdefault(page_index, []).append(str(item.title))
                elif isinstance(item, list):
                    walk(item)

        try:
            walk(outlines)
        except Exception:
            # defensive measure: returns whatever we collected if outlines are not as anticipated
            return outlines_map

        return outlines_map

    @staticmethod
    def _normalize_section_key(title: str | None) -> str | None:
        """
        Normalize a raw outline title into a section key used by strategies.

        This is intentionally simple for now and can be specialized for Drake conventions later.
        """
        if not title:
            return None

        normalized = title.strip().upper()

        # basic normalization: spaces and dashes -> underscores
        for ch in (" ", "-", "/"):
            normalized = normalized.replace(ch, "_")

        # collapse repeated underscores
        while "__" in normalized:
            normalized = normalized.replace("__", "_")

        # Example of potential specialization (update w/ more Drake Patterns):
        # if "CLIENT" in normalized and "LETTER" in normalized:
        #   return "CLIENT LETTER"
        # if normalized.startswith("BILL"):
        #   return "BILL_01"

        return normalized or None
