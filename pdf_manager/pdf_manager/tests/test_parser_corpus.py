"""Integration tests against local Drake sample PDFs (gitignored)."""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from pdf_manager.apps.parser.facade import PDFParserFacade

SAMPLES_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "drake_samples"
SCORP_SAMPLE = SAMPLES_DIR / "TEST S CORP_NO WATER MARK.pdf"


@pytest.mark.skipif(not SCORP_SAMPLE.is_file(), reason="Drake sample PDFs not present locally")
def test_parse_scorp_extracts_core_fields():
    facade = PDFParserFacade()
    result = facade.parse(job_id=uuid4(), file_path=str(SCORP_SAMPLE))

    fields = result.extracted_fields
    assert fields.get("ocr_attempted_count", 0) <= 2
    assert fields.get("message_ready") is True
    assert fields.get("taxpayer_tin") == "987654321"
    assert result.message
    assert "Hi " in result.message
    assert result.output_subset_path.is_file()
    assert any(tp.tags[0].label == "extract_client_letter" for tp in result.tagged_pages)


@pytest.mark.skipif(not SCORP_SAMPLE.is_file(), reason="Drake sample PDFs not present locally")
def test_parse_scorp_builds_signature_packet():
    facade = PDFParserFacade()
    result = facade.parse(job_id=uuid4(), file_path=str(SCORP_SAMPLE))

    assert result.signature_packet_path is not None
    assert result.signature_packet_path.is_file()
