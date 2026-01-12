from __future__ import annotations

from abc import ABC, abstractmethod

from pdf_manager.apps.parser.types import TaggedPage


class ReorderStrategy(ABC):
    name = "base"

    @abstractmethod
    def order(self, pages: list[TaggedPage]) -> list[int]:
        raise NotImplementedError
