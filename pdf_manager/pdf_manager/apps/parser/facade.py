from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from django.conf import settings

from .events import (
    EVT_FIELDS_EXTRACTED,
    EVT_INGESTION_COMPLETED,
    EVT_INPUT_VALIDATED,
    EVT_MESSAGE_GENERATED,
    EVT_PAGES_TAGGED,
    EVT_SUBSET_WRITTEN,
    Event,
    EventBus,
)
from .exceptions import InputValidationError
from .ingestion import ingest_local_file
from .message_builder import build_message
from .packet_builder import build_packet_orders
from .registry import (
    ADAPTERS_PDF_READER,
    STRATEGIES_FIELD_EXTRACTION,
    STRATEGIES_PAGE_CLASSIFIER,
    STRATEGIES_REORDER,
)
from .types import PageTag, ParseResult, TaggedPage, Template


def _default_pdf_reader() -> str:
    return getattr(settings, "PARSER_PDF_READER", "pymupdf")


def _default_page_classifier() -> str:
    return getattr(settings, "PARSER_PAGE_CLASSIFIER", "drake")


class PDFParserFacade:
    def __init__(
        self,
        event_bus: EventBus | None = None,
        pdf_reader: str | None = None,
        page_classifier: str | None = None,
        field_extractor: str = "regex",
        reorders: str = "template_rules",
    ) -> None:
        self.event_bus = event_bus or EventBus()

        reader_key = pdf_reader or _default_pdf_reader()
        classifier_key = page_classifier or _default_page_classifier()

        self._pdf_reader_cls = ADAPTERS_PDF_READER[reader_key]
        self._page_cls_cls = STRATEGIES_PAGE_CLASSIFIER[classifier_key]
        self._field_ext_cls = STRATEGIES_FIELD_EXTRACTION[field_extractor]
        self._reorder_cls = STRATEGIES_REORDER[reorders]

    def run(self, input_path: str, template_key: str | None = None) -> ParseResult:
        job = ingest_local_file(Path(input_path), template_key=template_key)

        self._publish(
            EVT_INGESTION_COMPLETED,
            {
                "job_id": job.job_id,
                "original_name": job.file.original_name,
                "stored_path": str(job.file.stored_path),
                "size_bytes": job.file.size_bytes,
                "sha256": job.file.sha256,
                "template_key": job.template_key,
            },
        )

        job_uuid = UUID(hex=job.job_id) if len(job.job_id) == 32 else UUID(str(job.job_id))
        return self.parse(job_id=job_uuid, file_path=str(job.file.stored_path))

    def parse(self, job_id: UUID, file_path: str) -> ParseResult:
        input_path = Path(file_path)
        self._validate_input(input_path)

        self._publish(EVT_INPUT_VALIDATED, {"job_id": str(job_id), "path": str(input_path)})

        reader = self._pdf_reader_cls(input_path)
        try:
            pages = reader.pages()

            page_classifier = self._page_cls_cls()
            page_tags = page_classifier.tag_pages(pages)
            tagged_pages: list[TaggedPage] = [
                TaggedPage(page=p, tags=tags) for p, tags in zip(pages, page_tags, strict=False)
            ]
            self._publish(EVT_PAGES_TAGGED, {"count": len(tagged_pages)})

            template = Template(name="DRAKE", version="1")
            field_extractor = self._field_ext_cls()
            extracted = field_extractor.extract(tagged_pages, template)
            self._publish(EVT_FIELDS_EXTRACTED, {"fields_count": len(extracted)})

            reorder = self._reorder_cls()
            base_order = reorder.order(tagged_pages)

            main_order, signature_indices, voucher_indices = build_packet_orders(
                tagged_pages, base_order
            )

            outputs_dir = Path(settings.OUTPUTS_DIR) / str(job_id)
            outputs_dir.mkdir(parents=True, exist_ok=True)

            main_subset_path = outputs_dir / f"Tax Document_{job_id}.pdf"
            main_subset_path = reader.write_subset(main_order, main_subset_path)

            signature_subset_path: Path | None = None
            if signature_indices:
                signature_subset_path = outputs_dir / f"Signature Requested_{job_id}.pdf"
                signature_subset_path = reader.write_subset(signature_indices, signature_subset_path)

            payment_voucher_subset_path: Path | None = None
            if voucher_indices:
                payment_voucher_subset_path = outputs_dir / f"Instructions to Pay Due Tax_{job_id}.pdf"
                payment_voucher_subset_path = reader.write_subset(
                    voucher_indices, payment_voucher_subset_path
                )

            self._publish(
                EVT_SUBSET_WRITTEN,
                {
                    "output": str(main_subset_path),
                    "pages": main_order,
                    "signature_output": str(signature_subset_path) if signature_subset_path else None,
                    "signature_pages": signature_indices,
                    "payment_voucher_output": (
                        str(payment_voucher_subset_path) if payment_voucher_subset_path else None
                    ),
                    "payment_voucher_pages": voucher_indices,
                },
            )

            templates_dir = Path(__file__).parent / "templates" / "messages"
            temp_result = SimpleNamespace(
                extracted_fields=extracted,
                payment_voucher_packet_path=payment_voucher_subset_path,
            )
            message = ""
            if extracted.get("message_ready"):
                message = build_message(temp_result, templates_dir, template_key="generic")
            self._publish(
                EVT_MESSAGE_GENERATED,
                {"message": message, "message_ready": bool(extracted.get("message_ready"))},
            )

            return ParseResult(
                job_id=job_id,
                input_path=input_path,
                output_subset_path=main_subset_path,
                message=message,
                extracted_fields=extracted,
                tagged_pages=tagged_pages,
                signature_packet_path=signature_subset_path,
                payment_voucher_packet_path=payment_voucher_subset_path,
            )
        finally:
            close = getattr(reader, "close", None)
            if callable(close):
                close()

    def _validate_input(self, path: Path) -> None:
        if not path.exists() or not path.is_file():
            raise InputValidationError(f"File not found: {path}")

    def _publish(self, name: str, payload: dict) -> None:
        self.event_bus.publish(Event(name=name, payload=payload))
