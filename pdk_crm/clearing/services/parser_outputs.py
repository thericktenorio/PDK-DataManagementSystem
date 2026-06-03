"""Parser output download metadata for clearing UI (Phase 4.6)."""
from __future__ import annotations

from typing import Any

from django.urls import reverse

from core.models import ProductAssignment

OUTPUT_KIND_LABELS: dict[str, str] = {
    "main_packet": "Tax document packet",
    "all_outputs": "Signature & payment PDFs (ZIP)",
}


def parser_output_kinds(pa: ProductAssignment) -> set[str]:
    if not pa.parse_job_uuid or not pa.parser_output_refs:
        return set()
    return {str(ref.get("kind")) for ref in pa.parser_output_refs if ref.get("kind")}


def parser_download_items(pa: ProductAssignment) -> list[dict[str, str]]:
    """Return display rows for template or JSON (kind + label only)."""
    if not pa.parse_job_uuid or not pa.parser_output_refs:
        return []

    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for ref in pa.parser_output_refs:
        kind = str(ref.get("kind") or "")
        if kind not in OUTPUT_KIND_LABELS or kind in seen:
            continue
        items.append({"kind": kind, "label": OUTPUT_KIND_LABELS[kind]})
        seen.add(kind)
    return items


def parser_downloads_payload(pa: ProductAssignment, *, pa_id: int | None = None) -> list[dict[str, Any]]:
    """Download list with relative CRM proxy URLs."""
    pk = pa_id if pa_id is not None else pa.pk
    downloads: list[dict[str, Any]] = []
    for item in parser_download_items(pa):
        downloads.append(
            {
                **item,
                "url": reverse(
                    "clearing:parser_output_download",
                    kwargs={"pa_id": pk, "kind": item["kind"]},
                ),
            }
        )
    return downloads
