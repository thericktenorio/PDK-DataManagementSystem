"""Persist schema v1 extracted fields on ParseJob (Phase 5)."""
from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from pdf_manager.apps.core.models import ExtractedField, ParseJob, Template
from pdf_manager.apps.parser.extraction_schema import (
    DRAKE_TEMPLATE_NAME,
    DRAKE_TEMPLATE_VERSION,
    EXTRACTED_FIELD_KEYS,
)


def get_drake_template() -> Template | None:
    return Template.objects.filter(
        name=DRAKE_TEMPLATE_NAME,
        version=DRAKE_TEMPLATE_VERSION,
    ).first()


def _value_to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, default=str)
    return str(value)


def persist_extracted_fields(
    *,
    job: ParseJob,
    document,
    template: Template | None,
    fields: dict[str, Any],
) -> int:
    """
    Replace per-job ExtractedField rows with catalog keys present in ``fields``.
    """
    sources = fields.get("_field_sources") or {}
    if not isinstance(sources, dict):
        sources = {}

    ExtractedField.objects.filter(parse_job=job).delete()

    rows: list[ExtractedField] = []
    for key in EXTRACTED_FIELD_KEYS:
        if key not in fields:
            continue
        value = fields[key]
        if value is None or value == "":
            continue

        meta = sources.get(key) if isinstance(sources.get(key), dict) else {}
        method = str(meta.get("method") or "")
        page_index = meta.get("page_index")
        if page_index is not None:
            try:
                page_index = int(page_index)
            except (TypeError, ValueError):
                page_index = None

        rows.append(
            ExtractedField(
                document=document,
                parse_job=job,
                template=template,
                key=key,
                value=_value_to_text(value),
                confidence=Decimal("1.000"),
                extraction_method=method[:16],
                source_page_index=page_index,
            )
        )

    if rows:
        ExtractedField.objects.bulk_create(rows)
    return len(rows)
