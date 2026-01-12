from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pdf_manager.apps.parser.types import TaggedPage, Template


class FieldExtractionStrategy(ABC):
    name = "base"

    @abstractmethod
    def extract(self, pages: list[TaggedPage], template: Template) -> dict[str, Any]:
        raise NotImplementedError
