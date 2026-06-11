"""Enrollment signal extraction unit + corpus tests."""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from pdf_manager.apps.parser.enrollment_signals import (
    _extract_preparer_name_from_diagnostic,
    build_enrollment_signals,
    extract_comparison_enrollment_signals,
    scan_outline_enrollment_signals,
)
from pdf_manager.apps.parser.facade import PDFParserFacade
from pdf_manager.apps.parser.types import OutlineInfo, PdfPage, TaggedPage

SAMPLES_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "drake_samples"
TEST_PERSONAL = SAMPLES_DIR / "TEST PERSONAL_NO WATER MARK.pdf"
TEST_SCORP = SAMPLES_DIR / "TEST S CORP_NO WATER MARK.pdf"
TEST_PERSONAL_TPG = SAMPLES_DIR / "TEST PERSONAL_TPG & EPAYMENTS.pdf"

DIAGNOSTIC_TEXT = """Diagnostic Summary
Preparer:
Invoice # and Amount:
RICARDO TENORIO
 $675.00
11-11-2025
Return Information
"""

COMPARISON_PERSONAL_TEXT = """2024
TAX RETURN COMPARISON
Name(s) as shown on return
Identifying number
Filing Status
Number of Dependents
Total itemized deductions
Standard deduction
Credits
JOHN & JANE DOE
123-45-6789
Married Joint
Married Joint
1
1
1
55,000
55,000
29,200
29,200
2,000
2,000
2,000
"""


def _tagged_page(title: str, *, index: int = 0) -> TaggedPage:
    return TaggedPage(
        page=PdfPage(index=index, raw=None, outline=OutlineInfo(title=title)),
        tags=[],
    )


def test_diagnostic_preparer_name():
    assert _extract_preparer_name_from_diagnostic(DIAGNOSTIC_TEXT) == "RICARDO TENORIO"


def test_comparison_dependents_itemizing_and_credits():
    signals = extract_comparison_enrollment_signals(COMPARISON_PERSONAL_TEXT)
    assert signals["comparison_num_dependents"] == 1
    assert signals["comparison_itemized_deductions"] == 55_000
    assert signals["comparison_standard_deduction"] == 29_200
    assert signals["comparison_credits"] == 2_000


def test_outline_corporation_and_amendment_scan():
    pages = [
        _tagged_page("1120S"),
        _tagged_page("1040X"),
        _tagged_page("Client Letter"),
    ]
    signals = scan_outline_enrollment_signals(pages)
    assert signals["is_corporation"] is True
    assert signals["amendment_count"] == 1


def test_outline_sole_prop_schedules():
    pages = [
        _tagged_page("Schedule C (Net Profit from Business)"),
        _tagged_page("Schedule E (Rental Income) Page 2"),
    ]
    signals = scan_outline_enrollment_signals(pages)
    assert signals["has_sole_prop_schedule"] is True


def test_build_enrollment_signals_merges_sources():
    pages = [
        _tagged_page("Schedule C (Net Profit from Business)"),
        _tagged_page("4868"),
    ]
    signals = build_enrollment_signals(
        pages=pages,
        comparison_text=COMPARISON_PERSONAL_TEXT,
        diagnostic_text=DIAGNOSTIC_TEXT,
        has_tpg_pages=False,
    )
    assert signals["has_sole_prop_schedule"] is True
    assert signals["has_extension"] is True
    assert signals["preparer_name"] == "RICARDO TENORIO"
    assert signals["comparison_num_dependents"] == 1


@pytest.mark.skipif(not TEST_PERSONAL.is_file(), reason="Drake sample PDFs not present locally")
def test_parse_personal_enrollment_signals_sole_prop_over_itemizing():
    result = PDFParserFacade().parse(job_id=uuid4(), file_path=str(TEST_PERSONAL))
    signals = result.extracted_fields.get("enrollment_signals") or {}
    assert signals.get("has_sole_prop_schedule") is True
    assert signals.get("comparison_itemized_deductions", 0) > signals.get(
        "comparison_standard_deduction", 0
    )
    assert signals.get("preparer_name") == "RICARDO TENORIO"
    assert result.extracted_fields.get("has_tpg_pages") is False


@pytest.mark.skipif(not TEST_SCORP.is_file(), reason="Drake sample PDFs not present locally")
def test_parse_scorp_enrollment_signals_corporation():
    result = PDFParserFacade().parse(job_id=uuid4(), file_path=str(TEST_SCORP))
    signals = result.extracted_fields.get("enrollment_signals") or {}
    assert signals.get("is_corporation") is True
    assert signals.get("has_extension") is False
    assert int(signals.get("amendment_count") or 0) == 0


@pytest.mark.skipif(not TEST_PERSONAL_TPG.is_file(), reason="Drake sample PDFs not present locally")
def test_parse_personal_tpg_sets_has_tpg_pages():
    result = PDFParserFacade().parse(job_id=uuid4(), file_path=str(TEST_PERSONAL_TPG))
    assert result.extracted_fields.get("has_tpg_pages") is True
    signals = result.extracted_fields.get("enrollment_signals") or {}
    assert signals.get("has_tpg_pages") is True
