from __future__ import annotations

from .adapters.pdf_reader_base import PdfReaderAdapter
from .adapters.pdf_reader_pypdf2 import PyPDF2Reader
from .strategies.field_extraction_base import FieldExtractionStrategy
from .strategies.field_extraction_regex import RegexFieldExtraction
from .strategies.page_classification_base import PageClassificationStrategy
from .strategies.page_classification_heuristic import HeuristicClassifier
from .strategies.reorder_base import ReorderStrategy
from .strategies.reorder_template_rules import TemplateRuleReorder

ADAPTERS_PDF_READER: dict[str, type[PdfReaderAdapter]] = {
    "pypdf2": PyPDF2Reader,
}

STRATEGIES_PAGE_CLASSIFIER: dict[str, type[PageClassificationStrategy]] = {
    "heuristic": HeuristicClassifier,
}

STRATEGIES_FIELD_EXTRACTION: dict[str, type[FieldExtractionStrategy]] = {
    "regex": RegexFieldExtraction,
}

STRATEGIES_REORDER: dict[str, type[ReorderStrategy]] = {"template_rules": TemplateRuleReorder}
