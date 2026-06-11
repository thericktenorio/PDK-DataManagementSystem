"""Fee and name extraction unit + corpus tests."""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from pdf_manager.apps.parser.facade import PDFParserFacade
from pdf_manager.apps.parser.strategies.field_extraction_regex import (
    _extract_bill_page2_fee,
    _extract_customer_bank_from_dd_pmt,
    _extract_diagnostic_invoice_fee,
    _extract_name_and_address_from_client_letter,
    _extract_tax_prep_fee,
    _extract_tpg_info_fee,
)

SAMPLES_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "drake_samples"

SAMPLE_A = SAMPLES_DIR / "SampleA_Personal_TPG_EPayments_NoWaterMark copy.pdf"
TEST_PERSONAL = SAMPLES_DIR / "TEST PERSONAL_NO WATER MARK.pdf"
TEST_SCORP = SAMPLES_DIR / "TEST S CORP_NO WATER MARK.pdf"

CLIENT_LETTER_OCR = """PDK ENTRUST
1207 ROBIN PLACE
CHULA VISTA, CA 91911
November 11, 2025
John & Jane Doe
1600 Pennsylvania Ave NW
San Diego, CA 92154
John & Jane Doe:
Below is a summary of your 2024 tax year.
Federal Income Tax due April 15, 2025
Internal Revenue Service
P.O. Box 931000
Louisville, KY 40293-1000
"""

TPG_INFO_TEXT = """BANK PRODUCT INFORMATION
Tax Preparation Fee
Paid to
PDK ENTRUST
1,000.00
"""

DIAGNOSTIC_TEXT = """Diagnostic Summary
Preparer:
Invoice # and Amount:
RICARDO TENORIO
 $675.00
11-11-2025
Return Information
"""

BILL_PAGE2_OCR = """Forms Subtotal 1,050.00
Total Balance Due 1,050.00
Payment due upon receipt. Thank you for your business!
"""


def test_client_letter_name_uses_first_taxpayer_block():
    fields = _extract_name_and_address_from_client_letter(CLIENT_LETTER_OCR)
    assert fields["taxpayer_first_name"] == "John"
    assert fields["taxpayer_full_name"] == "John & Jane Doe"
    assert fields["mailing_city"] == "San Diego"


SCORP_CLIENT_LETTER_OCR = """PDK ENTRUST
1207 ROBIN PLACE
CHULA VISTA, CA 91911
November 11, 2025
TEST S CORP
123 Main Street
San Diego, CA 92154
TEST S CORP:
Below is a summary of your 2024 tax year.
"""


def test_client_letter_entity_name_uses_full_legal_name():
    fields = _extract_name_and_address_from_client_letter(SCORP_CLIENT_LETTER_OCR)
    assert fields["taxpayer_full_name"] == "Test S Corp"
    assert fields["taxpayer_first_name"] == "Test S Corp"
    assert fields.get("taxpayer_is_entity") is True


def test_fee_priority_tpg_over_diagnostic():
    fee, role = _extract_tax_prep_fee(
        tpg_text=TPG_INFO_TEXT,
        diagnostic_text=DIAGNOSTIC_TEXT,
        bill_fee_text=BILL_PAGE2_OCR,
    )
    assert fee == 1000.0
    assert role == "extract_tpg_fee"


DD_PMT_SNIPPET = """The total refund (minus fees if Applicable) will be direct deposited into
the customer's chosen bank account:
Financial Institution
NAVY FEDERAL CREDIT UNION
Routing Transit Number
256074974
Account Number
000000000000000
Account Type
Checking
"""


def test_dd_pmt_extracts_customer_bank_and_last4():
    fields = _extract_customer_bank_from_dd_pmt(DD_PMT_SNIPPET)
    assert fields["bank_name"] == "NAVY FEDERAL CREDIT UNION"
    assert fields["last_4_of_account"] == "0000"


def test_fee_extractors():
    assert _extract_tpg_info_fee(TPG_INFO_TEXT) == 1000.0
    assert _extract_diagnostic_invoice_fee(DIAGNOSTIC_TEXT) == 675.0
    assert _extract_bill_page2_fee(BILL_PAGE2_OCR) == 1050.0


@pytest.mark.skipif(not SAMPLE_A.is_file(), reason="Drake sample PDFs not present locally")
def test_parse_sample_a_name_and_tpg_fee():
    result = PDFParserFacade().parse(job_id=uuid4(), file_path=str(SAMPLE_A))
    fields = result.extracted_fields
    assert fields.get("taxpayer_first_name") == "John"
    assert fields.get("taxpayer_full_name") == "John & Jane Doe"
    assert fields.get("tax_prep_fee") == 1000.0
    assert fields.get("taxpayer_tin") == "123456789"
    assert fields.get("message_ready") is True
    assert fields.get("bank_name") == "NAVY FEDERAL CREDIT UNION"
    assert fields.get("last_4_of_account") == "0000"
    assert "Hi John" in result.message


@pytest.mark.skipif(not TEST_PERSONAL.is_file(), reason="Drake sample PDFs not present locally")
def test_parse_test_personal_invoice_fee():
    result = PDFParserFacade().parse(job_id=uuid4(), file_path=str(TEST_PERSONAL))
    fields = result.extracted_fields
    assert fields.get("taxpayer_first_name") == "John"
    assert fields.get("tax_prep_fee") == 675.0
    assert fields.get("has_tpg_pages") is False
    assert fields.get("taxpayer_tin") == "123456789"


@pytest.mark.skipif(not TEST_SCORP.is_file(), reason="Drake sample PDFs not present locally")
def test_parse_scorp_bill_page2_fee():
    result = PDFParserFacade().parse(job_id=uuid4(), file_path=str(TEST_SCORP))
    fields = result.extracted_fields
    assert fields.get("taxpayer_first_name") == "Test S Corp"
    assert fields.get("tax_prep_fee") == 1050.0
    assert fields.get("taxpayer_tin") == "987654321"
