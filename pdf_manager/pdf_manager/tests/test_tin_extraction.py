"""Taxpayer TIN extraction unit tests (Path A global upload foundation)."""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from pdf_manager.apps.parser.facade import PDFParserFacade
from pdf_manager.apps.parser.strategies.field_extraction_regex import (
    _extract_taxpayer_tin,
    _extract_tin_from_comparison,
    _extract_tin_from_diagnostic,
    _extract_tin_from_1040,
    _normalize_tin_value,
)

SAMPLES_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "drake_samples"
TEST_PERSONAL = SAMPLES_DIR / "TEST PERSONAL_NO WATER MARK.pdf"
TEST_SCORP = SAMPLES_DIR / "TEST S CORP_NO WATER MARK.pdf"

DIAGNOSTIC_PERSONAL_TEXT = """Diagnostic Summary
Return Information
Name(s)
Taxpayer Tax ID Number
Spouse Tax Id Number
JOHN & JANE DOE
123-45-6789
987-65-4321
"""

DIAGNOSTIC_SCORP_TEXT = """Diagnostic Summary
Name
Employer Identification #
TEST S CORP
98-7654321
"""

COMPARISON_TEXT = """TAX RETURN COMPARISON
Name(s) as shown on return
Identifying number
JOHN & JANE DOE
123-45-6789
  Married Joint
"""

FORM_1040_TEXT = """1040 U.S. Individual Income Tax Return
Your social security number
123-45-6789
987-65-4321
"""


def test_normalize_tin_strips_dashes():
    assert _normalize_tin_value("123-45-6789") == "123456789"
    assert _normalize_tin_value("98-7654321") == "987654321"


def test_extract_tin_from_diagnostic_personal_primary_ssn():
    assert _extract_tin_from_diagnostic(DIAGNOSTIC_PERSONAL_TEXT) == "123456789"


def test_extract_tin_from_diagnostic_scorp_ein():
    assert _extract_tin_from_diagnostic(DIAGNOSTIC_SCORP_TEXT) == "987654321"


def test_extract_tin_from_comparison_joint_primary():
    assert _extract_tin_from_comparison(COMPARISON_TEXT) == "123456789"


def test_extract_tin_from_1040_first_ssn():
    assert _extract_tin_from_1040(FORM_1040_TEXT) == "123456789"


def test_taxpayer_tin_priority_diagnostic_over_comparison():
    tin, role = _extract_taxpayer_tin(
        diagnostic_text=DIAGNOSTIC_PERSONAL_TEXT,
        comparison_text=COMPARISON_TEXT,
        form_1040_text=FORM_1040_TEXT,
    )
    assert tin == "123456789"
    assert role == "extract_diagnostic_invoice"


def test_taxpayer_tin_falls_back_to_comparison():
    tin, role = _extract_taxpayer_tin(
        diagnostic_text="",
        comparison_text=COMPARISON_TEXT,
        form_1040_text=FORM_1040_TEXT,
    )
    assert tin == "123456789"
    assert role == "extract_tin_comparison"


def test_taxpayer_tin_falls_back_to_1040():
    tin, role = _extract_taxpayer_tin(
        diagnostic_text="",
        comparison_text="",
        form_1040_text=FORM_1040_TEXT,
    )
    assert tin == "123456789"
    assert role == "form_federal"


@pytest.mark.skipif(not TEST_PERSONAL.is_file(), reason="Drake sample PDFs not present locally")
def test_parse_personal_extracts_taxpayer_tin():
    result = PDFParserFacade().parse(job_id=uuid4(), file_path=str(TEST_PERSONAL))
    assert result.extracted_fields.get("taxpayer_tin") == "123456789"


@pytest.mark.skipif(not TEST_SCORP.is_file(), reason="Drake sample PDFs not present locally")
def test_parse_scorp_extracts_entity_tin():
    result = PDFParserFacade().parse(job_id=uuid4(), file_path=str(TEST_SCORP))
    assert result.extracted_fields.get("taxpayer_tin") == "987654321"
