"""Ack hint extraction unit tests (parser ack hints backlog)."""
from pdf_manager.apps.parser.ack_hints import (
    apply_ack_hints,
    extract_efiled_transmissions_from_client_letter,
    extract_state_filings_from_diagnostic,
    extract_transmissions_from_bill,
    merge_expected_transmissions,
)

CLIENT_LETTER_EFILED = """
Refund/Balance Due Transaction Method
Federal Income Tax Refund $1,200.00 Direct Deposit
California Income Tax Balance Due $50.00 Mail

The following returns will be e-filed:
Federal    1040
California 540

Sign and date where indicated below.
"""

CLIENT_LETTER_FEDERAL_ONLY = """
The following returns will be e-filed:
Federal Income Tax Return    1040
Sign and date
"""

DIAGNOSTIC_STATES = """
Diagnostic Summary
State Returns
California    CA540
Hawaii        HIN15
Return Information
"""

BILL_INDEX = """
Forms Included
1040    U.S. Individual Income Tax Return
CA540   California Resident Income Tax Return
8879    IRS e-file Signature Authorization
1120S   U.S. Income Tax Return for an S Corporation
"""


def test_client_letter_efiled_federal_and_state():
    tx = extract_efiled_transmissions_from_client_letter(CLIENT_LETTER_EFILED)
    forms = {t["form_type"] for t in tx}
    assert "1040" in forms
    assert "CA540" in forms
    assert len(tx) == 2


def test_client_letter_federal_only():
    tx = extract_efiled_transmissions_from_client_letter(CLIENT_LETTER_FEDERAL_ONLY)
    assert len(tx) == 1
    assert tx[0]["form_type"] == "1040"
    assert tx[0]["jurisdiction"] == "federal"


def test_diagnostic_state_filings():
    tx = extract_state_filings_from_diagnostic(DIAGNOSTIC_STATES)
    forms = {t["form_type"] for t in tx}
    assert forms == {"CA540", "HIN15"}


def test_bill_index_excludes_signature_forms():
    tx = extract_transmissions_from_bill(BILL_INDEX)
    forms = {t["form_type"] for t in tx}
    assert "8879" not in forms
    assert "1040" in forms
    assert "CA540" in forms
    assert "1120S" in forms


def test_merge_dedupes_by_form_type():
    letter = extract_efiled_transmissions_from_client_letter(CLIENT_LETTER_EFILED)
    diagnostic = extract_state_filings_from_diagnostic(DIAGNOSTIC_STATES)
    merged = merge_expected_transmissions(letter, diagnostic)
    forms = {t["form_type"] for t in merged}
    assert forms == {"1040", "CA540", "HIN15"}


def test_apply_ack_hints_priority_client_letter():
    out: dict = {}
    apply_ack_hints(
        out,
        client_letter_text=CLIENT_LETTER_EFILED,
        diagnostic_text=DIAGNOSTIC_STATES,
        bill_text=BILL_INDEX,
    )
    assert out["expected_ack_count"] == 3
    assert out["expected_ack_source"] == "client_letter"
    assert len(out["expected_transmissions"]) == 3


def test_apply_ack_hints_fallback_diagnostic():
    out: dict = {}
    apply_ack_hints(
        out,
        client_letter_text="",
        diagnostic_text=DIAGNOSTIC_STATES,
        bill_text=BILL_INDEX,
    )
    assert out["expected_ack_count"] == 4
    assert out["expected_ack_source"] == "diagnostic"


def test_apply_ack_hints_fallback_bill():
    out: dict = {}
    apply_ack_hints(out, bill_text=BILL_INDEX)
    assert out["expected_ack_count"] == 3
    assert out["expected_ack_source"] == "bill"


def test_apply_ack_hints_empty_when_no_signal():
    out: dict = {"taxpayer_first_name": "Jane"}
    apply_ack_hints(out)
    assert "expected_ack_count" not in out
