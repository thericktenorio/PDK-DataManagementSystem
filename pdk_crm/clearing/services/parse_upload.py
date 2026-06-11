"""
Apply pdf_manager parse results to a ProductAssignment (Phase 4.4–4.6).
"""
from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from core.models import Client, ParserStatus, ProductAssignment
from core.workflows.lifecycle import is_pa_locked_for_editing

from clearing.services.parser_schema import (
    build_parse_result_snapshot,
    build_parser_output_refs,
    suggest_pa_field_updates,
    sync_client_name_from_parse_fields,
)
from clearing.services.pdf_manager_client import PDFManagerClient, PDFManagerError


class ParseUploadError(Exception):
    """User-facing parse/upload failure."""


_TIN_RE = re.compile(r"\D+")


def _normalize_tin(value: str | None) -> str | None:
    if not value:
        return None
    digits = _TIN_RE.sub("", str(value))
    return digits if len(digits) == 9 else None


def _require_conflict_flow_for_board(pa: ProductAssignment) -> None:
    """Per-row upload must use the global conflict modal when client is on the board."""
    from clearing.services.global_parse import build_match_payload

    if build_match_payload(pa.client).get("on_clearing"):
        raise ParseUploadError(
            "This client is already on clearing. "
            "Choose Replace Entry or New Entry in the upload conflict dialog."
        )


def _validate_row_tin_match(pa: ProductAssignment, detail: dict[str, Any]) -> None:
    fields = detail.get("fields") or {}
    if not isinstance(fields, dict):
        return
    tin = _normalize_tin(fields.get("taxpayer_tin"))
    client_tin = (pa.client.TIN or "").strip()
    if tin and client_tin and tin != client_tin:
        raise ParseUploadError(
            "Uploaded TIN does not match this clearing entry. "
            "Use Upload Tax PDF from the header to enroll the correct client."
        )


def _apply_parser_detail_to_pa(
    pa: ProductAssignment,
    *,
    job_id: UUID | str,
    detail: dict[str, Any],
) -> dict[str, Any]:
    snapshot = build_parse_result_snapshot(job_id=job_id, detail=detail)
    output_refs = build_parser_output_refs(job_id=job_id, detail=detail)
    quality = snapshot.get("quality") or {}
    message_ready = bool(quality.get("message_ready"))
    field_updates = suggest_pa_field_updates(snapshot.get("fields") or {})
    message_text = (snapshot.get("message") or "").strip() if message_ready else ""
    client = pa.client
    name_updated = False

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

        if "preparer_id" in field_updates:
            pa.preparer_id = field_updates["preparer_id"]
            update_fields.append("preparer")

        pa.save(update_fields=update_fields)

        fields = snapshot.get("fields") or {}
        client = Client.objects.select_for_update().get(pk=pa.client_id)
        name_updated = sync_client_name_from_parse_fields(client, fields)

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
        "client_name": client.name if name_updated else None,
    }


def apply_parser_from_job(
    pa: ProductAssignment,
    parse_job_uuid: UUID | str,
    *,
    client: PDFManagerClient | None = None,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply an existing pdf_manager job to a PA (global upload commit path)."""
    if is_pa_locked_for_editing(pa):
        raise ParseUploadError("Cannot parse PDF while clearing row is locked.")

    pdf_client = client or PDFManagerClient()
    if detail is None:
        try:
            detail = pdf_client.get_job(parse_job_uuid, detail=True)
        except PDFManagerError as exc:
            raise ParseUploadError(str(exc)) from exc

    job_id = detail.get("job_id") or str(parse_job_uuid)
    _validate_row_tin_match(pa, detail)
    return _apply_parser_detail_to_pa(pa, job_id=job_id, detail=detail)


def apply_parser_pdf(
    pa: ProductAssignment,
    uploaded_file,
    *,
    client: PDFManagerClient | None = None,
    parse_job_uuid: UUID | str | None = None,
) -> dict[str, Any]:
    """
    Upload PDF to pdf_manager (or reuse parse_job_uuid), store snapshots on PA.

    Path B remains available on failure (caller handles ParseUploadError).
    """
    if is_pa_locked_for_editing(pa):
        raise ParseUploadError("Cannot parse PDF while clearing row is locked.")

    _require_conflict_flow_for_board(pa)

    pdf_client = client or PDFManagerClient()

    if parse_job_uuid is not None:
        return apply_parser_from_job(pa, parse_job_uuid, client=pdf_client)

    filename = getattr(uploaded_file, "name", "") or "upload.pdf"
    if not filename.lower().endswith(".pdf"):
        raise ParseUploadError("Only PDF files are supported.")

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

    _validate_row_tin_match(pa, detail)
    return _apply_parser_detail_to_pa(pa, job_id=job_id, detail=detail)
