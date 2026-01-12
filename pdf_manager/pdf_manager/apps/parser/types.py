from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class FileMeta:
    original_name: str
    stored_path: Path
    size_bytes: int
    sha256: str
    content_type: str = "application/pdf"


@dataclass(frozen=True)
class OutlineInfo:
    """
    Structural metadata for a page in the original source PDF.

    - title: raw outline/bookmark node title from the PDF.
    - path: full path from the root outline, eg "Federal", "1040" etc
    - section_key: normalized key used by strategies, eg "CLIENT_LETTER", "BILL_01"
    """

    title: str
    path: tuple[str, ...] = field(default_factory=tuple)
    section_key: str | None = None


@dataclass
class ParseJob:
    "Represents a single end-to-end parse run."

    job_id: str
    template_key: str | None
    file: FileMeta
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    extra: dict[str, str] = field(default_factory=dict)

    @property
    def outputs_dir(self) -> Path:
        from django.conf import settings

        return Path(settings.OUTPUTS_DIR) / self.job_id

    @property
    def output_pdf_path(self) -> Path:
        return self.outputs_dir / f"{self.job_id}.pdf"

    def ensure_outputs_dir(self) -> None:
        self.outputs_dir.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class PdfPage:
    index: int
    raw: Any  # backend-specific handle
    outline: OutlineInfo | None = None
    source_path: Path | None = None


@dataclass(frozen=True)
class PageTag:
    label: str
    score: float = 1.0
    meta: dict[str, Any] | None = None


@dataclass(frozen=True)
class TaggedPage:
    page: PdfPage
    tags: list[PageTag]

    @property
    def index(self) -> int:
        return self.page.index

    @property
    def outline(self) -> OutlineInfo | None:
        return self.page.outline

    @property
    def section_key(self) -> str | None:
        return self.page.outline.section_key if self.page.outline else None


@dataclass(frozen=True)
class Template:
    name: str
    version: str | None = None
    config: dict[str, Any] | None = None


@dataclass(frozen=True)
class ParseResult:
    job_id: UUID
    input_path: Path
    output_subset_path: Path  # main cleaned/reordered packet
    message: str
    extracted_fields: dict[str, Any]
    tagged_pages: list[TaggedPage]
    signature_packet_path: Path | None = None
    payment_voucher_packet_path: Path | None = None
