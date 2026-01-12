from __future__ import annotations

from pdf_manager.apps.parser.strategies.reorder_base import ReorderStrategy
from pdf_manager.apps.parser.types import TaggedPage


class TemplateRuleReorder(ReorderStrategy):
    name = "template_rules"

    def order(self, pages: list[TaggedPage]) -> list[int]:
        # identity order for Phase 2
        return [tp.page.index for tp in pages]
