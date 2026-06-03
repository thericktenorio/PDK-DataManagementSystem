"""PyMuPDF PDF reader — outlines, text extraction, and subset writes."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path

import fitz

from pdf_manager.apps.parser.adapters.pdf_reader_base import PdfReaderAdapter
from pdf_manager.apps.parser.drake_registry import normalize_section_key
from pdf_manager.apps.parser.types import OutlineInfo, PdfPage


class PyMuPDFReader(PdfReaderAdapter):
    def __init__(self, file_path: Path) -> None:
        super().__init__(file_path)
        self.file_path = file_path
        try:
            self.doc = fitz.open(str(file_path))
        except Exception as exc:
            raise RuntimeError(f"Failed to open PDF with PyMuPDF: {file_path}") from exc

    def pages(self) -> list[PdfPage]:
        outlines_map = self.outlines_by_page()
        pages: list[PdfPage] = []
        for i in range(self.doc.page_count):
            titles = outlines_map.get(i) or []
            outline_info: OutlineInfo | None = None
            if titles:
                title = str(titles[0])
                outline_info = OutlineInfo(
                    title=title,
                    path=tuple(titles),
                    section_key=normalize_section_key(title),
                )
            pages.append(
                PdfPage(
                    index=i,
                    raw=None,
                    outline=outline_info,
                    source_path=self.file_path,
                )
            )
        return pages

    def extract_text(self, page_idx: int) -> str:
        try:
            return self.doc[page_idx].get_text("text") or ""
        except Exception:
            return ""

    def write_subset(self, page_order: Sequence[int], out_path: Path) -> Path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        subset = fitz.open()
        try:
            for i in page_order:
                subset.insert_pdf(self.doc, from_page=i, to_page=i)
            subset.save(str(out_path))
        finally:
            subset.close()
        return out_path

    def outlines_by_page(self) -> dict[int, list[str]]:
        outlines_map: dict[int, list[str]] = defaultdict(list)
        try:
            toc = self.doc.get_toc(simple=True) or []
        except Exception:
            return {}
        for _level, title, page_num in toc:
            idx = max(int(page_num) - 1, 0)
            outlines_map[idx].append(str(title))
        return dict(outlines_map)

    def close(self) -> None:
        if self.doc is not None:
            self.doc.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass
