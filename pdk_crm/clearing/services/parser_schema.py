"""
Parser Result Schema v1 — CRM snapshot stored on ProductAssignment.parse_result_json.

Full parse jobs live in pdf_manager; CRM keeps only references + extracted-field snapshots.
See docs/PARSER_EXTRACTION.md for tier definitions.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

SCHEMA_VERSION = 1

# Re-export catalog keys (keep in sync with pdf_manager extraction_schema).
EXTRACTED_FIELD_KEYS: tuple[str, ...] = (
    "taxpayer_first_name",
    "taxpayer_full_name",
    "taxpayer_tin",
    "tax_year",
    "federal_amount",
    "states",
    "last_4_of_account",
    "bank_name",
    "mailing_address",
    "mailing_address_line1",
    "mailing_city",
    "mailing_state",
    "mailing_zip",
    "tax_prep_fee",
    "has_tpg_pages",
    "enrollment_signals",
    "expected_transmissions",
    "expected_ack_count",
    "expected_ack_source",
)

INTERNAL_FIELD_KEYS = frozenset({
    "ocr_enabled",
    "ocr_attempted_count",
    "ocr_success_count",
    "ocr_total_ms",
    "message_ready",
    "message_ready_reason",
    "taxpayer_is_entity",
    "_field_sources",
})

ENTITY_NAME_MARKERS: tuple[str, ...] = (
    " CORP",
    " LLC",
    " INC",
    " LP",
    " LLP",
    " LTD",
    " PLLC",
    " CO.",
    " COMPANY",
    " S CORP",
    " SCORP",
    " L.L.C.",
    " L.P.",
)


def is_entity_taxpayer(fields: dict[str, Any]) -> bool:
    full = (fields.get("taxpayer_full_name") or "").strip()
    if not full:
        return False
    upper = full.upper()
    return any(marker in upper for marker in ENTITY_NAME_MARKERS)


def sync_client_name_from_parse_fields(client, fields: dict[str, Any]) -> bool:
    """Update CRM Client.name from entity return legal name when extracted."""
    full = (fields.get("taxpayer_full_name") or "").strip()
    if not full or not is_entity_taxpayer(fields):
        return False
    if client.name != full:
        client.name = full
        client.save(update_fields=["name"])
        return True
    return False


def _public_fields(fields: dict[str, Any]) -> dict[str, Any]:
    return {
        k: v
        for k, v in fields.items()
        if k in EXTRACTED_FIELD_KEYS and k not in INTERNAL_FIELD_KEYS
    }


def build_quality(fields: dict[str, Any]) -> dict[str, Any]:
    return {
        "message_ready": bool(fields.get("message_ready")),
        "message_ready_reason": fields.get("message_ready_reason"),
    }


def build_parse_result_snapshot(*, job_id: UUID | str, detail: dict[str, Any]) -> dict[str, Any]:
    """Normalize pdf_manager job detail payload into CRM parse_result_json."""
    fields = detail.get("fields") or {}
    if not isinstance(fields, dict):
        fields = {}

    return {
        "schema_version": SCHEMA_VERSION,
        "job_id": str(job_id),
        "fields": _public_fields(fields),
        "quality": build_quality(fields),
        "message": detail.get("message") or "",
        "pages": detail.get("pages") or [],
        "outputs": {
            "main_packet": detail.get("output_pdf_path"),
            "signature": detail.get("signature_pdf_path"),
            "payment_voucher": detail.get("payment_voucher_pdf_path"),
        },
    }


def build_parser_output_refs(
    *,
    job_id: UUID | str,
    detail: dict[str, Any],
    base_url: str | None = None,
) -> list[dict[str, str]]:
    """
    CRM-facing references to parser output PDFs.

    Download URLs are built at request time via clearing proxy views (Phase 4.6).
    ``base_url`` is accepted for backward compatibility but not stored on refs.
    """
    _ = base_url
    job_str = str(job_id)
    refs: list[dict[str, str]] = []

    if detail.get("output_pdf_path"):
        refs.append({"kind": "main_packet", "job_id": job_str})

    extra_kinds: list[str] = []
    if detail.get("signature_pdf_path"):
        extra_kinds.append("signature")
    if detail.get("payment_voucher_pdf_path"):
        extra_kinds.append("payment_voucher")

    if extra_kinds:
        refs.append(
            {
                "kind": "all_outputs",
                "job_id": job_str,
                "includes": ",".join(extra_kinds),
            }
        )

    return refs


def suggest_pa_field_updates(fields: dict[str, Any]) -> dict[str, Any]:
    """
    Map extracted parser fields to optional PA auto-fill values.
    Staff can override before completing clearing.
    """
    updates: dict[str, Any] = {}

    tax_prep_fee = fields.get("tax_prep_fee")
    if tax_prep_fee is not None:
        updates["fee"] = str(tax_prep_fee)

    from core.models import ProductAssignment

    if fields.get("has_tpg_pages"):
        updates["payment_method"] = ProductAssignment.PAYMENT_METHOD_TPG
    else:
        updates["payment_method"] = ProductAssignment.PAYMENT_METHOD_QBO

    signals = fields.get("enrollment_signals") or {}
    if isinstance(signals, dict):
        from clearing.services.enrollment_inference import match_preparer_id

        preparer_id = match_preparer_id(signals)
        if preparer_id:
            updates["preparer_id"] = preparer_id

    return updates


def parse_result_fields(pa) -> dict[str, Any]:
    """Return extracted field map from PA parse_result_json, or empty dict."""
    snapshot = pa.parse_result_json or {}
    fields = snapshot.get("fields") or {}
    return fields if isinstance(fields, dict) else {}


def suggested_expected_ack_count(pa) -> int | None:
    """
    Parser-derived expected ack count for Review Complete modal prefill.

    Staff can override; returns None when no parser hint (default modal value 1).
    """
    fields = parse_result_fields(pa)
    count = fields.get("expected_ack_count")
    if count is None:
        return None
    try:
        parsed = int(count)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 1 else None
