"""Phase 5 corpus timing benchmark (optional local Drake samples)."""
from __future__ import annotations

import time
from pathlib import Path
from uuid import uuid4

import pytest
from django.conf import settings

from pdf_manager.apps.parser.facade import PDFParserFacade

SAMPLES_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "drake_samples"
SCORP_SAMPLE = SAMPLES_DIR / "TEST S CORP_NO WATER MARK.pdf"
MAX_SECONDS = float(getattr(settings, "PARSER_BENCHMARK_MAX_SECONDS", 5.0))


@pytest.mark.skipif(not SCORP_SAMPLE.is_file(), reason="Drake sample PDFs not present locally")
def test_parse_scorp_under_benchmark_budget():
    facade = PDFParserFacade()
    start = time.perf_counter()
    result = facade.parse(job_id=uuid4(), file_path=str(SCORP_SAMPLE))
    elapsed = time.perf_counter() - start

    assert elapsed < MAX_SECONDS, f"parse took {elapsed:.2f}s (budget {MAX_SECONDS}s)"
    assert result.extracted_fields.get("message_ready") is True
    assert result.message
    assert result.extracted_fields.get("ocr_attempted_count", 0) <= 1
