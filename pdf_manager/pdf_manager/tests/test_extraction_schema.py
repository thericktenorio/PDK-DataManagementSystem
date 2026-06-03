"""Phase 5 extraction schema tests."""
from pdf_manager.apps.parser.extraction_schema import (
    finalize_extracted_fields,
    public_fields,
    quality_payload,
)


def test_finalize_sets_message_ready_with_name_and_year():
    raw = {"taxpayer_first_name": "Jane", "tax_year": "2024"}
    out = finalize_extracted_fields(raw)
    assert out["message_ready"] is True
    assert "message_ready_reason" not in out


def test_finalize_first_name_from_full_name():
    raw = {"taxpayer_full_name": "john & jane doe", "tax_year": "2024"}
    out = finalize_extracted_fields(raw)
    assert out["taxpayer_first_name"] == "John"
    assert out["message_ready"] is True


def test_finalize_missing_name_not_message_ready():
    raw = {"tax_year": "2024"}
    out = finalize_extracted_fields(raw)
    assert out["message_ready"] is False
    assert out["message_ready_reason"] == "missing_taxpayer_first_name"


def test_public_fields_strips_internal_keys():
    raw = {
        "taxpayer_first_name": "A",
        "message_ready": True,
        "ocr_total_ms": 100,
        "_field_sources": {},
    }
    pub = public_fields(raw)
    assert pub == {"taxpayer_first_name": "A"}
    assert quality_payload(raw)["message_ready"] is True
