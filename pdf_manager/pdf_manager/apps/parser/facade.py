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
from .registry import (
    ADAPTERS_PDF_READER,
    STRATEGIES_FIELD_EXTRACTION,
    STRATEGIES_PAGE_CLASSIFIER,
    STRATEGIES_REORDER,
)
from .types import PageTag, ParseResult, TaggedPage, Template


# Facade which orchestrates end-to-end functions of parsing
class PDFParserFacade:
    def __init__(
        self,
        event_bus: EventBus | None = None,
        pdf_reader: str = "pypdf2",
        page_classifier: str = "heuristic",
        field_extractor: str = "regex",
        reorders: str = "template_rules",
    ) -> None:
        self.event_bus = event_bus or EventBus()

        # Resolve adapters/strategies
        self._pdf_reader_cls = ADAPTERS_PDF_READER[pdf_reader]
        self._page_cls_cls = STRATEGIES_PAGE_CLASSIFIER[page_classifier]
        self._field_ext_cls = STRATEGIES_FIELD_EXTRACTION[field_extractor]
        self._reorder_cls = STRATEGIES_REORDER[reorders]

    # Public entry point (preferred): performs ingestion, then full parse pipeline
    def run(self, input_path: str, template_key: str | None = None) -> ParseResult:
        """
        End-to-end convenience entry:
        1) Ingest file into /data/incoming (checksum, size, AV stub).
        2) Execute parse pipeline using the stored path.
        """
        job = ingest_local_file(Path(input_path), template_key=template_key)

        # Publish ingestion completion (for audit trail)
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

        # Normalize job_id to UUID
        job_uuid = UUID(hex=job.job_id) if len(job.job_id) == 32 else UUID(str(job.job_id))
        return self.parse(job_id=job_uuid, file_path=str(job.file.stored_path))

    # Core pipeline (kept compatible with your existing tests/tools):
    def parse(self, job_id: UUID, file_path: str) -> ParseResult:
        input_path = Path(file_path)
        self._validate_input(input_path)

        self._publish(EVT_INPUT_VALIDATED, {"job_id": str(job_id), "path": str(input_path)})

        # Instantiate collaborators
        reader = self._pdf_reader_cls(input_path)
        pages = reader.pages()

        # Tagging
        page_classifier = self._page_cls_cls()
        page_tags = page_classifier.tag_pages(pages)
        tagged_pages: list[TaggedPage] = [
            TaggedPage(page=p, tags=tags) for p, tags in zip(pages, page_tags, strict=False)
        ]
        self._publish(EVT_PAGES_TAGGED, {"count": len(tagged_pages)})

        # Extraction (template would be chosen upstream or inferred)
        template = Template(name="GENERIC", version="0")
        field_extractor = self._field_ext_cls()
        extracted = field_extractor.extract(tagged_pages, template)
        self._publish(EVT_FIELDS_EXTRACTED, {"fields_count": len(extracted)})

        # ------------------------------------------------------------------
        # Reorder + packet building (main cleaned packet + signature packet + payment voucher)
        # ------------------------------------------------------------------
        reorder = self._reorder_cls()
        base_order = reorder.order(tagged_pages)  # list[int] page indices ()

        # Build index -> tags mapping for quick lookups
        tags_by_idx: dict[int, list[PageTag]] = {tp.page.index: tp.tags for tp in tagged_pages}

        # Define removal and cover labels
        REMOVAL_LABELS = {
            "EF_STATUS",
            "FILING_MESSAGE",
            "STATE_FILING_MESSAGE",
            "NOTES",
            "ADMIN",
        }

        def is_unwanted(idx: int) -> bool:
            return any(t.label in REMOVAL_LABELS for t in tags_by_idx.get(idx, []))

        def is_cover(idx: int) -> bool:
            return any(t.label == "COVER" for t in tags_by_idx.get(idx, []))

        def is_signature(idx: int) -> bool:
            return any(t.label == "SIGNATURE" for t in tags_by_idx.get(idx, []))

        def is_payment_voucher(idx: int) -> bool:
            return any(t.label == "PAYMENT_VOUCHER" for t in tags_by_idx.get(idx, []))

        # 1) Signature packet indices (sorted)
        signature_indices = sorted(
            {tp.page.index for tp in tagged_pages if is_signature(tp.page.index)}
        )
        signature_set = set(signature_indices)

        # 2) Payment voucher packet indices
        voucher_indices = sorted(
            {tp.page.index for tp in tagged_pages if is_payment_voucher(tp.page.index)}
        )
        voucher_set = set(voucher_indices)

        # 3) Clean main order: start from reorder's base_order
        #   - drop unwanted pages
        #   - drop signature pages (they go only into the signature packet)
        filtered_order = [
            i
            for i in base_order
            if not is_unwanted(i) and i not in signature_set and i not in voucher_set
        ]

        cover_indices = [i for i in filtered_order if is_cover(i)]
        non_cover_indices = [i for i in filtered_order if not is_cover(i)]

        # 4) Covers first, then all other remaining pages
        main_order = cover_indices + non_cover_indices

        # Write the subset(s) into /data/outputs/{job_id}/{job_id}.pdf
        outputs_dir = Path(settings.OUTPUTS_DIR) / str(job_id)
        outputs_dir.mkdir(parents=True, exist_ok=True)

        # Main cleaned/reordered packet
        main_subset_path = outputs_dir / f"Tax Document_{job_id}.pdf"
        main_subset_path = reader.write_subset(main_order, main_subset_path)

        # Signature packet
        signature_subset_path: Path | None = None
        if signature_indices:
            signature_subset_path = outputs_dir / f"Signature Requested_{job_id}.pdf"
            signature_subset_path = reader.write_subset(signature_indices, signature_subset_path)

        # Payment voucher
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

        # -------------------------------------------------------
        # Message generation (dynamic, based on extracted fields)
        # -------------------------------------------------------
        templates_dir = Path(__file__).parent / "templates" / "messages"

        # build lightweight object that has attributes expected by build_message:
        # - .extracted_fields
        # - .payment_voucher_packet_path
        temp_result = SimpleNamespace(
            extracted_fields=extracted,
            payment_voucher_packet_path=payment_voucher_subset_path,
        )

        message = build_message(
            temp_result,
            templates_dir,
            template_key=getattr(template, "name", None),
        )
        self._publish(EVT_MESSAGE_GENERATED, {"message": message})

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

    def _validate_input(self, path: Path) -> None:
        if not path.exists() or not path.is_file():
            raise InputValidationError(f"File not found: {path}")
        # ingestion enforces size/extension/AV stub; this check is minimal.

    def _publish(self, name: str, payload: dict) -> None:
        self.event_bus.publish(Event(name=name, payload=payload))
