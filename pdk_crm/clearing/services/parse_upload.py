"""
Apply pdf_manager parse results to a ProductAssignment (Phase 4.4–4.6).
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from core.models import ParserStatus, ProductAssignment
from core.workflows.lifecycle import is_pa_locked_for_editing

from clearing.services.parser_schema import (
    build_parse_result_snapshot,
    build_parser_output_refs,
    suggest_pa_field_updates,
)
from clearing.services.pdf_manager_client import PDFManagerClient, PDFManagerError


class ParseUploadError(Exception):
    """User-facing parse/upload failure."""


def apply_parser_pdf(
    pa: ProductAssignment,
    uploaded_file,
    *,
    client: PDFManagerClient | None = None,
) -> dict[str, Any]:
    """
    Upload PDF to pdf_manager, store snapshots on PA, auto-fill clearing fields.

    Path B remains available on failure (caller handles ParseUploadError).
    """
    if is_pa_locked_for_editing(pa):
        raise ParseUploadError("Cannot parse PDF while clearing row is locked.")

    filename = getattr(uploaded_file, "name", "") or "upload.pdf"
    if not filename.lower().endswith(".pdf"):
        raise ParseUploadError("Only PDF files are supported.")

    pdf_client = client or PDFManagerClient()

    try:
        uploaded_file.seek(0)
        detail = pdf_client.upload_and_fetch_detail(
            file_obj=uploaded_file,
            filename=filename,
        )
    except PDFManagerError as exc:
        raise ParseUploadError(str(exc)) from exc

    job_id = detail.get("job_id")
    if not job_id:
        raise ParseUploadError("Parser did not return a job id.")

    snapshot = build_parse_result_snapshot(job_id=job_id, detail=detail)
    output_refs = build_parser_output_refs(
        job_id=job_id,
        detail=detail,
    )
    raw_fields = detail.get("fields") or {}
    if not isinstance(raw_fields, dict):
        raw_fields = {}
    quality = snapshot.get("quality") or {}
    message_ready = bool(quality.get("message_ready"))
    field_updates = suggest_pa_field_updates(snapshot.get("fields") or {})
    message_text = (snapshot.get("message") or "").strip() if message_ready else ""

    with transaction.atomic():
        pa = ProductAssignment.objects.select_for_update().get(pk=pa.pk)

        pa.parse_job_uuid = UUID(str(job_id))
        pa.parse_result_json = snapshot
        pa.parsed_at = timezone.now()
        pa.parser_output_refs = output_refs
        pa.parser_status = ParserStatus.DONE

        update_fields = [
            "parse_job_uuid",
            "parse_result_json",
            "parsed_at",
            "parser_output_refs",
            "parser_status",
        ]

        if message_text:
            pa.closing_message_text = message_text
            update_fields.append("closing_message_text")

        if "fee" in field_updates:
            pa.fee = field_updates["fee"]
            update_fields.append("fee")

        if "payment_method" in field_updates:
            pa.payment_method = field_updates["payment_method"]
            update_fields.append("payment_method")

        pa.save(update_fields=update_fields)

    return {
        "parse_job_uuid": str(job_id),
        "parsed_at": pa.parsed_at.isoformat(),
        "message_text": pa.closing_message_text or "",
        "message_ready": message_ready,
        "message_ready_reason": quality.get("message_ready_reason"),
        "fee": str(pa.fee) if pa.fee is not None else "",
        "payment_method": pa.payment_method or "",
        "parser_output_refs": output_refs,
        "fields": snapshot.get("fields") or {},
    }
