from __future__ import annotations

from abc import abstractmethod
from collections.abc import Sequence
from pathlib import Path

from ..types import PdfPage  # noqa: TID252


class PdfReaderAdapter:
    """Contract for PDF readers used by the pipeline."""

    def __init__(self, file_path: Path) -> None:
        self.file_path = file_path

    @abstractmethod
    def pages(self) -> list[PdfPage]:
        """Return an index-stable list of PdfPage wrappers (index + raw handle)."""
        raise NotImplementedError

    @abstractmethod
    def extract_text(self, page_idx: int) -> str:
        """Extract visible text from the page at index."""
        raise NotImplementedError

    @abstractmethod
    def write_subset(self, page_order: Sequence[int], out_path: Path) -> Path:
        """Write a new PDF composed of the selected page indices (0-based)."""
        raise NotImplementedError

    def outlines_by_page(self) -> dict[int, list[str]]:
        """
        Optional hoo: return mapping of original page index -> list of outline titles
        associated with that page in the source PDF. Concrete adapters may override.
        """
        return {}
