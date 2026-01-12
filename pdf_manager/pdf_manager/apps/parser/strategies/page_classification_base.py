from __future__ import annotations

from abc import ABC, abstractmethod

from pdf_manager.apps.parser.types import PageTag, PdfPage


class PageClassificationStrategy(ABC):
    name = "base"

    @abstractmethod
    def tag_pages(self, pages: list[PdfPage]) -> list[list[PageTag]]:
        raise NotImplementedError
