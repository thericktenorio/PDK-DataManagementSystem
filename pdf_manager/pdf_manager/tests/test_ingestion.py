from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from pdf_manager.apps.parser.events import EVT_INGESTION_COMPLETED, Event, EventBus
from pdf_manager.apps.parser.facade import PDFParserFacade
from pdf_manager.apps.parser.ingestion import ingest_local_file
from pdf_manager.apps.parser.types import ParseResult


@pytest.mark.django_db
def test_ingest_local_file_moves_and_hashes(tmp_path: Path, settings):
    # Redirect data dirs to tmp to avoid writing into repo tree
    settings.DATA_ROOT = tmp_path / "data"
    settings.INCOMING_DIR = settings.DATA_ROOT / "incoming"
    settings.OUTPUTS_DIR = settings.DATA_ROOT / "outputs"
    settings.INCOMING_DIR.mkdir(parents=True, exist_ok=True)
    settings.OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

    # Minimal "PDF" content is fine for ingestion (we don't parse here)
    src = tmp_path / "sample.pdf"
    src.write_bytes(b"%PDF-1.7\n%EOF\n")

    job = ingest_local_file(src, template_key="w2")

    # Basics
    assert job.job_id

    # Destination and metadata
    stored = job.file.stored_path
    assert stored.exists()
    assert stored.parent.resolve() == Path(settings.INCOMING_DIR).resolve()
    assert job.file.size_bytes == stored.stat().st_size
    assert isinstance(job.file.sha256, str)
    assert len(job.file.sha256) == 64

    # Outputs dir created for the job
    assert job.outputs_dir.exists()


@dataclass
class RecordingObserver:
    events: list[Event] = field(default_factory=list)

    def on_event(self, event: Event) -> None:
        self.events.append(event)


@pytest.mark.django_db
def test_facade_run_emits_ingestion_completed(tmp_path: Path, settings, monkeypatch):
    # Redirect data dirs to tmp
    settings.DATA_ROOT = tmp_path / "data"
    settings.INCOMING_DIR = settings.DATA_ROOT / "incoming"
    settings.OUTPUTS_DIR = settings.DATA_ROOT / "outputs"
    settings.INCOMING_DIR.mkdir(parents=True, exist_ok=True)
    settings.OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

    # Prepare a tiny "PDF" for ingestion
    src = tmp_path / "mini.pdf"
    src.write_bytes(b"%PDF-1.7\n%EOF\n")

    # Write a bus with recording observer
    bus = EventBus()
    recorder = RecordingObserver()
    bus.subscribe(recorder)

    # TODO: This is just patch parse() for development. Remove before production
    def _fake_parse(self, job_id, file_path: str) -> ParseResult:
        out_dir = Path(settings.OUTPUTS_DIR) / str(job_id)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_pdf = out_dir / f"{job_id}.pdf"
        out_pdf.write_bytes(b"%PDF-1.7\n%EOF\n")
        return ParseResult(
            job_id=job_id,
            input_path=Path(file_path),
            output_subset_path=out_pdf,
            message="(stub) Parsed 0 pages; extracted 0 fields.",
            extracted_fields={},
            tagged_pages=[],
        )

    monkeypatch.setattr(PDFParserFacade, "parse", _fake_parse, raising=True)

    facade = PDFParserFacade(event_bus=bus)
    result = facade.run(input_path=str(src), template_key="w2")

    # Assert ingestion event was published
    names = [e.name for e in recorder.events]
    assert EVT_INGESTION_COMPLETED in names

    # Sanity checks on stubbed result
    assert result.input_path.exists()
    assert result.output_subset_path.exists()
