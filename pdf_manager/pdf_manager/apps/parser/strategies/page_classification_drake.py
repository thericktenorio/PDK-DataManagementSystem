"""Drake outline registry page classifier (production default)."""
from __future__ import annotations

from pdf_manager.apps.parser.drake_registry import load_drake_registry
from pdf_manager.apps.parser.strategies.page_classification_base import PageClassificationStrategy
from pdf_manager.apps.parser.types import PageTag, PdfPage


def _outline_titles(page: PdfPage) -> list[str]:
    outline = getattr(page, "outline", None)
    if outline and outline.title:
        return [str(outline.title)]
    return []


class DrakeOutlineClassifier(PageClassificationStrategy):
    """
    Classify pages using Drake bookmark titles and outline_registry.yaml rules.
    Tag label = registry role (e.g. extract_client_letter, signature, remove).
    """

    name = "drake"

    def __init__(self) -> None:
        self.registry = load_drake_registry()

    def tag_pages(self, pages: list[PdfPage]) -> list[list[PageTag]]:
        tagged: list[list[PageTag]] = []
        for page in pages:
            titles = _outline_titles(page)
            role = self.registry.role_for_titles(titles)
            tagged.append([PageTag(label=role, score=0.99, meta={"outline_titles": titles})])
        return tagged
