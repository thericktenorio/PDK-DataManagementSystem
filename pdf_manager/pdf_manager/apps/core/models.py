from __future__ import annotations

import uuid

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


# Representative of PDF document
class Document(TimeStampedModel):
    filename = models.CharField(max_length=255)
    checksum = models.CharField(max_length=64, unique=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="documents",
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)
    page_count = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "doc_document"
        indexes = [
            models.Index(fields=["created_at"], name="doc_created_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"Document(id={self}, filename={self.filename})"


# Page of PDF document, used for extraction and classification (tagging)
class Page(TimeStampedModel):
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="pages")
    index = models.PositiveBigIntegerField()
    text_excerpt = models.TextField(blank=True)
    tag = models.CharField(max_length=64, blank=True)

    class Meta:
        db_table = "doc_page"
        unique_together = ("document", "index")
        indexes = [
            models.Index(fields=["document"], name="page_document_idx"),
            models.Index(fields=["created_at"], name="page_created_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"Page(doc = {self.document}, idx = {self.index})"


# Template : serves as the charter for how to classify/interpret pages for a specific document type
#           as well as tells the system how to extract named fields
class Template(TimeStampedModel):
    name = models.CharField(max_length=128)
    version = models.CharField(max_length=32, default="1.0")
    description = models.TextField(blank=True)
    rules_json = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "doc_template"
        unique_together = ("name", "version")
        indexes = [
            models.Index(fields=["created_at"], name="tpl_created_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"Template({self.name}) v{self.version}"


# Structured results from a Template being applied to a document
class ExtractedField(TimeStampedModel):
    document = models.ForeignKey(
        Document, on_delete=models.CASCADE, related_name="extracted_fields"
    )
    template = models.ForeignKey(
        Template, on_delete=models.SET_NULL, null=True, blank=True, related_name="fields"
    )
    key = models.CharField(max_length=128)
    value = models.TextField(blank=True)
    confidence = models.DecimalField(
        max_digits=4,
        decimal_places=3,
        default=1.000,
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
    )

    class Meta:
        db_table = "doc_extracted_field"
        indexes = [
            models.Index(fields=["document"], name="ef_document_idx"),
            models.Index(fields=["template"], name="ef_template_idx"),
            models.Index(fields=["created_at"], name="ef_created_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"ExtractedField(doc={self.document}, key={self.key})"


# Policy for selecting and ordering pages that have been output
class ReorderRule(TimeStampedModel):
    template = models.ForeignKey(Template, on_delete=models.CASCADE, related_name="reorder_rules")
    spec_json = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "doc_reorder_rule"
        indexes = [
            models.Index(fields=["template"], name="rr_template_idx"),
            models.Index(fields=["created_at"], name="rr_created_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"ReorderRule(template={self.template})"


# Track state and timing of a single parse execution
class ParseJob(TimeStampedModel):
    """
    Notes:
    - job_uuid is the public-facing/IO identifier (used by the facade and output paths)
    - result_* fields store a denormalized snapshot for fast UI rendering; can still
    persist detailed structures to Page/ExtractedField for analytics/reporting later.
    """

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        SUCCESS = "SUCCESS", "Success"
        FAILED = "FAILED", "Failed"

    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="parse_jobs")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    errors_json = models.JSONField(default=list, blank=True)

    # for public references, filesystem layout, and facade integration
    job_uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)

    # denormalized UI payload (fast to fetch on /api/jobs/{id}?detail=1)
    result_fields = models.JSONField(null=True, blank=True)
    result_pages = models.JSONField(null=True, blank=True)
    result_message = models.TextField(null=True, blank=True)

    # main cleaned/reordered packet for the job
    output_pdf_path = models.TextField(null=True, blank=True)

    # path for signature doc pdf
    signature_pdf_path = models.TextField(null=True, blank=True)

    # payment voucher doc pdf
    payment_voucher_pdf_path = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "doc_parse_job"
        indexes = [
            models.Index(fields=["document"], name="job_document_idx"),
            models.Index(fields=["created_at"], name="job_created_idx"),
            models.Index(fields=["job_uuid"], name="job_uuid_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover
        doc_id = getattr(self, "document_id", None)
        return f"ParseJob(doc={doc_id}, status={self.status}, uuid={self.job_uuid})"


# Append-only event log for a ParseJob
class AuditEvent(TimeStampedModel):
    class Level(models.TextChoices):
        INFO = "INFO", "Info"
        WARN = "WARN", "Warn"
        ERROR = "ERROR", "Error"

    job = models.ForeignKey(ParseJob, on_delete=models.CASCADE, related_name="audit_events")
    level = models.CharField(max_length=8, choices=Level.choices, default=Level.INFO)
    event_type = models.CharField(max_length=64)
    payload_json = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "doc_audit_event"
        indexes = [
            models.Index(fields=["job"], name="ae_job_idx"),
            models.Index(fields=["created_at"], name="ae_created_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"AuditEvent(job={self.job}, type={self.event_type})"
