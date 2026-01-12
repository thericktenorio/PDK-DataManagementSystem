from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .ingestion import ingest_local_file
from .registry import ADAPTERS_PDF_READER, STRATEGIES_PAGE_CLASSIFIER
from .types import PageTag


@dataclass(frozen=True)
class PageIntrospection:
    """
    Phase 7.0: lightweight view of single page for human inspection.
    """

    index: int
    tags: list[PageTag]
    text_preview: str
    outline_titles: list[str]


def introspect_local_file(
    input_path: Path,
    pdf_reader: str = "pypdf2",
    page_classifier: str = "heuristic",
) -> tuple[str, Path, list[PageIntrospection]]:
    """
    Ingest a local PDF and return a per-page introspection summary.

    Returns:
        [job_id, stored_path, [PageIntrospection, ...]]
    """
    # 1) Ingest using same logic as main pipeline
    job = ingest_local_file(input_path)

    # 2) Instantiate reader and classifier from the registry
    reader_cls = ADAPTERS_PDF_READER[pdf_reader]
    reader = reader_cls(job.file.stored_path)

    classifier_cls = STRATEGIES_PAGE_CLASSIFIER[page_classifier]
    classifier = classifier_cls()

    pages = reader.pages()
    page_tags = classifier.tag_pages(pages)

    # 3) Optionally get outlines per page (adapter-specific)
    outlines_by_page: dict[int, list[str]] = {}
    if hasattr(reader, "outlines_by_page"):
        outlines_by_page = reader.outlines_by_page()

    # 4) Build per-page introspection objects
    results: list[PageIntrospection] = []
    for page, tags in zip(pages, page_tags, strict=False):
        # text preview
        text = reader.extract_text(page.index) or ""
        # normalize whitespace and trim
        compact = " ".join(text.split())
        if len(compact) > 200:
            compact = compact[:200] + "..."

        titles = outlines_by_page.get(page.index, [])

        results.append(
            PageIntrospection(
                index=page.index,
                tags=tags,
                text_preview=compact,
                outline_titles=titles,
            )
        )

    return job.job_id, job.file.stored_path, results
