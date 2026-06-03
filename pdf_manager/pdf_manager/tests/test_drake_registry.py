from __future__ import annotations

from pathlib import Path

import pytest

from pdf_manager.apps.parser.drake_registry import load_drake_registry


@pytest.fixture
def registry():
    load_drake_registry.cache_clear()
    return load_drake_registry()


def test_client_letter_and_bill_roles(registry):
    assert registry.role_for_title("Client Letter") == "extract_client_letter"
    assert registry.role_for_title("Client Letter page 2") == "extract_client_letter"
    assert registry.role_for_title("BILL_01") == "extract_bill"
    assert registry.role_for_title("BILL_01 page 2") == "extract_bill"


def test_signature_and_voucher_roles(registry):
    assert registry.role_for_title("8879") == "signature"
    assert registry.role_for_title("Engagement Letter") == "signature"
    assert registry.role_for_title("1040V - Payment Voucher") == "payment_voucher"
    assert registry.role_for_title("California 3582-V") == "payment_voucher"


def test_remove_and_cover_roles(registry):
    assert registry.role_for_title("EF Messages") == "remove"
    assert registry.role_for_title("Notes") == "remove"
    assert registry.role_for_title("Folder Page") == "cover"
    assert registry.role_for_title("FILEINST") == "cover"


def test_packet_mapping(registry):
    assert registry.packet_for_role("signature") == "signature"
    assert registry.packet_for_role("payment_voucher") == "payment_voucher"
    assert registry.packet_for_role("remove") == "exclude"
    assert registry.packet_for_role("form_federal") == "main"


def test_ocr_roles(registry):
    assert registry.ocr_required_if_no_text("extract_client_letter")
    assert registry.ocr_required_if_no_text("extract_bill")
    assert not registry.ocr_required_if_no_text("form_federal")


def test_scorp_outline_roles(registry):
    assert registry.role_for_title("8879CORP") == "signature"
    assert registry.role_for_title("California 8453C") == "signature"
    assert registry.role_for_title("California 8453C Page 2") == "signature"
    assert registry.role_for_title("1120SK_1") == "form_k1"
    assert registry.role_for_title("1120SEF") == "form_federal"
    assert registry.role_for_title("California 100S") == "form_state"
    assert registry.role_for_title("California 100SK1 Page 2") == "form_k1"
    assert registry.role_for_title("Worksheet SCOMP") == "form_worksheet"


def test_main_section_order(registry):
    assert registry.main_section_order[0] == "cover"
    assert "extract_client_letter" in registry.main_section_order
    assert registry.main_role_rank("form_federal") < registry.main_role_rank("form_state")
