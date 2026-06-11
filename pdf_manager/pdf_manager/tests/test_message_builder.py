"""Client message conditional rules."""
from pdf_manager.apps.parser.message_builder import (
    build_due_tax_statement,
    build_message_context,
    build_refund_statement,
    build_tax_prep_fee_statement,
)


def test_refund_no_amounts_returns_empty():
    assert build_refund_statement(-100, [], None, "1 Main St") == ""


def test_refund_without_banking_uses_mailing_address():
    msg = build_refund_statement(
        500,
        [{"state": "CA", "amount": 100}],
        last4=None,
        mailing_address="1600 Pennsylvania Ave NW, San Diego CA 92154",
        bank_name=None,
    )
    assert "mailed to the following address" in msg
    assert "92154" in msg
    assert "direct deposited" not in msg


def test_refund_with_banking_uses_direct_deposit():
    msg = build_refund_statement(
        500,
        [],
        last4="1234",
        mailing_address="1600 Pennsylvania Ave NW, San Diego CA 92154",
        bank_name="NAVY FEDERAL CREDIT UNION",
    )
    assert "direct deposited into your NAVY FEDERAL CREDIT UNION account ending in 1234" in msg
    assert "mailed" not in msg


def test_refund_last4_only_without_bank_name_uses_mailing():
    msg = build_refund_statement(
        500,
        [],
        last4="1234",
        mailing_address="1 Main St",
        bank_name=None,
    )
    assert "mailed" in msg
    assert "direct deposited" not in msg


def test_refund_ignores_banking_when_no_refund_amount():
    msg = build_refund_statement(
        -500,
        [],
        last4="1234",
        mailing_address="1 Main St",
        bank_name="NAVY FEDERAL CREDIT UNION",
    )
    assert msg == ""


def test_tpg_fee_with_refund_uses_withhold_copy():
    msg = build_tax_prep_fee_statement(
        True,
        1000.0,
        federal_amount=500.0,
        states=[],
    )
    assert "deducted from your return" in msg
    assert "invoice" not in msg


def test_tpg_fee_with_balance_due_uses_invoice_copy():
    msg = build_tax_prep_fee_statement(
        True,
        1000.0,
        federal_amount=-500.0,
        states=[],
    )
    assert "invoice" in msg
    assert "deducted from your return" not in msg


def test_non_tpg_fee_uses_invoice_copy():
    msg = build_tax_prep_fee_statement(
        False,
        675.0,
        federal_amount=1200.0,
        states=[],
    )
    assert "invoice" in msg
    assert "deducted from your return" not in msg


def test_no_fee_returns_empty():
    assert build_tax_prep_fee_statement(True, None) == ""


def test_due_tax_with_voucher_packet():
    msg = build_due_tax_statement(True)
    assert "Instructions to pay owed taxes" in msg


def test_due_tax_with_balance_due_no_voucher():
    msg = build_due_tax_statement(
        False,
        federal_amount=-250.0,
        states=[{"state": "CA", "amount": 50.0}],
    )
    assert "Instructions to pay owed taxes" in msg


def test_due_tax_with_refund_only_returns_empty():
    msg = build_due_tax_statement(
        False,
        federal_amount=500.0,
        states=[],
    )
    assert msg == ""


def test_message_context_entity_greeting_uses_full_name():
    parse_result = type(
        "ParseResult",
        (),
        {
            "extracted_fields": {
                "taxpayer_first_name": "Test",
                "taxpayer_full_name": "Test S Corp",
                "taxpayer_is_entity": True,
                "tax_year": "2024",
            },
            "payment_voucher_packet_path": None,
        },
    )()
    ctx = build_message_context(parse_result)
    assert ctx["taxpayer_first_name"] == "Test S Corp"
