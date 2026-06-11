"""
Schema v1 extraction catalog and post-processing (Phase 5).

Aligns with docs/PARSER_EXTRACTION.md and CRM parser_schema.EXTRACTED_FIELD_KEYS.
"""
from __future__ import annotations

from typing import Any

SCHEMA_VERSION = 1

# Internal keys stored on ParseJob.result_fields but stripped from CRM-facing snapshots.
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


def looks_like_entity_name(name: str | None) -> bool:
    if not name:
        return False
    upper = str(name).upper()
    return any(marker in upper for marker in ENTITY_NAME_MARKERS)


def taxpayer_display_name(fields: dict[str, Any]) -> str:
    """Greeting name: full legal name for entities, first name for individuals."""
    full = (fields.get("taxpayer_full_name") or "").strip()
    first = (fields.get("taxpayer_first_name") or "").strip()
    if (fields.get("taxpayer_is_entity") or looks_like_entity_name(full)) and full:
        return full
    return first or full

# Keys persisted to ExtractedField rows and CRM snapshot.fields.
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

FIELD_CATALOG: tuple[dict[str, Any], ...] = (
    {
        "key": "taxpayer_first_name",
        "tier": "A",
        "source_roles": ("extract_client_letter",),
        "required_for_message": True,
    },
    {
        "key": "tax_year",
        "tier": "A",
        "source_roles": ("extract_client_letter",),
        "required_for_message": True,
    },
    {
        "key": "taxpayer_full_name",
        "tier": "C",
        "source_roles": ("extract_client_letter",),
        "required_for_message": False,
    },
    {
        "key": "taxpayer_tin",
        "tier": "A",
        "source_roles": (
            "extract_diagnostic_invoice",
            "extract_tin_comparison",
            "form_federal",
        ),
        "required_for_message": False,
    },
    {
        "key": "federal_amount",
        "tier": "B",
        "source_roles": ("extract_client_letter",),
        "required_for_message": False,
    },
    {
        "key": "states",
        "tier": "B",
        "source_roles": ("extract_client_letter",),
        "required_for_message": False,
    },
    {
        "key": "last_4_of_account",
        "tier": "B",
        "source_roles": ("extract_client_letter", "extract_dd_pmt"),
        "required_for_message": False,
    },
    {
        "key": "bank_name",
        "tier": "B",
        "source_roles": ("extract_dd_pmt",),
        "required_for_message": False,
    },
    {
        "key": "mailing_address",
        "tier": "B",
        "source_roles": ("extract_client_letter",),
        "required_for_message": False,
    },
    {
        "key": "mailing_address_line1",
        "tier": "C",
        "source_roles": ("extract_client_letter",),
        "required_for_message": False,
    },
    {
        "key": "mailing_city",
        "tier": "C",
        "source_roles": ("extract_client_letter",),
        "required_for_message": False,
    },
    {
        "key": "mailing_state",
        "tier": "C",
        "source_roles": ("extract_client_letter",),
        "required_for_message": False,
    },
    {
        "key": "mailing_zip",
        "tier": "C",
        "source_roles": ("extract_client_letter",),
        "required_for_message": False,
    },
    {
        "key": "tax_prep_fee",
        "tier": "B",
        "source_roles": (
            "extract_tpg_fee",
            "extract_diagnostic_invoice",
            "extract_bill_fee",
        ),
        "required_for_message": False,
    },
    {
        "key": "has_tpg_pages",
        "tier": "B",
        "source_roles": ("outline",),
        "required_for_message": False,
    },
    {
        "key": "expected_transmissions",
        "tier": "B",
        "source_roles": ("extract_client_letter", "extract_diagnostic_invoice", "extract_bill"),
        "required_for_message": False,
    },
    {
        "key": "expected_ack_count",
        "tier": "B",
        "source_roles": ("extract_client_letter", "extract_diagnostic_invoice", "extract_bill"),
        "required_for_message": False,
    },
)

DRAKE_TEMPLATE_NAME = "DRAKE"
DRAKE_TEMPLATE_VERSION = "1"


def finalize_extracted_fields(raw: dict[str, Any]) -> dict[str, Any]:
    """
    Apply Tier A rules: name fallback, message_ready flag, reason when not ready.
    """
    out = dict(raw)

    full_name = (out.get("taxpayer_full_name") or "").strip()
    is_entity = bool(out.get("taxpayer_is_entity")) or looks_like_entity_name(full_name)
    first = (out.get("taxpayer_first_name") or "").strip()

    if is_entity and full_name:
        first = full_name.title()
        out["taxpayer_full_name"] = first
        out["taxpayer_first_name"] = first
    elif not first and full_name:
        tokens = str(full_name).split()
        if tokens:
            first = tokens[0].title()
            out["taxpayer_first_name"] = first

    tax_year = str(out.get("tax_year") or "").strip()
    if tax_year:
        out["tax_year"] = tax_year

    if first and tax_year:
        out["message_ready"] = True
        out.pop("message_ready_reason", None)
    else:
        out["message_ready"] = False
        if not first:
            out["message_ready_reason"] = "missing_taxpayer_first_name"
        else:
            out["message_ready_reason"] = "missing_tax_year"

    return out


def public_fields(raw: dict[str, Any]) -> dict[str, Any]:
    """CRM/analytics field map without internal or debug keys."""
    return {
        k: v
        for k, v in raw.items()
        if k in EXTRACTED_FIELD_KEYS and v is not None and v != ""
    }


def quality_payload(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "message_ready": bool(raw.get("message_ready")),
        "message_ready_reason": raw.get("message_ready_reason"),
        "schema_version": SCHEMA_VERSION,
    }
