"""
Analytics warehouse models (Phase 9).

Stored in the separate `analytics` PostgreSQL database. Populated by ETL from
`tax_operations`; never written by operational workflows.
"""
from django.db import models


class EtlRun(models.Model):
    """Metadata for each warehouse sync."""

    class Status(models.TextChoices):
        RUNNING = "RUNNING", "Running"
        SUCCESS = "SUCCESS", "Success"
        FAILED = "FAILED", "Failed"

    started_at = models.DateTimeField(auto_now_add=True, db_index=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.RUNNING)
    is_full_refresh = models.BooleanField(default=False)
    rows_dimensions = models.PositiveIntegerField(default=0)
    rows_assignments = models.PositiveIntegerField(default=0)
    rows_invoices = models.PositiveIntegerField(default=0)
    rows_acks = models.PositiveIntegerField(default=0)
    rows_lifecycle_events = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return f"ETL {self.started_at:%Y-%m-%d %H:%M} ({self.status})"


class EtlWatermark(models.Model):
    """Incremental sync cursors (single row per entity key)."""

    entity = models.CharField(max_length=64, primary_key=True)
    last_int_id = models.BigIntegerField(null=True, blank=True)
    last_datetime = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.entity}: id={self.last_int_id} dt={self.last_datetime}"


class DimTaxSeason(models.Model):
    source_tax_season_id = models.PositiveIntegerField(unique=True)
    year = models.PositiveIntegerField(db_index=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=False)
    is_archived = models.BooleanField(default=False)
    synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-year"]

    def __str__(self):
        return f"Season {self.year}"


class DimClient(models.Model):
    source_client_id = models.PositiveIntegerField(unique=True)
    name = models.CharField(max_length=255, blank=True, default="")
    tin = models.CharField(max_length=9, blank=True, default="")
    email = models.EmailField(max_length=254, blank=True, default="")
    phone = models.CharField(max_length=32, blank=True, default="")
    filing_type = models.CharField(max_length=100, blank=True, default="")
    prior_filing_type = models.CharField(max_length=100, blank=True, default="")
    appointment_type = models.CharField(max_length=32, blank=True, default="")
    client_created_at = models.DateTimeField(null=True, blank=True)
    synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name or f"Client {self.source_client_id}"


class DimProduct(models.Model):
    source_product_id = models.PositiveIntegerField(unique=True)
    product_type = models.CharField(max_length=100, blank=True, default="")
    tax_year = models.SmallIntegerField(null=True, blank=True, db_index=True)
    default_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    synced_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.product_type} ({self.tax_year})"


class FactAssignment(models.Model):
    """
    One row per ProductAssignment — primary grain for KPI and turnover reporting.
    """

    source_pa_id = models.PositiveIntegerField(unique=True)
    source_client_id = models.PositiveIntegerField(db_index=True)
    tax_season_year = models.PositiveIntegerField(db_index=True)
    source_product_id = models.PositiveIntegerField(null=True, blank=True)
    source_intake_id = models.PositiveIntegerField(null=True, blank=True)

    lifecycle_state = models.CharField(max_length=32, blank=True, default="", db_index=True)
    payment_method = models.CharField(max_length=32, blank=True, default="")
    product_type = models.CharField(max_length=100, blank=True, default="")
    filing_type = models.CharField(max_length=100, blank=True, default="")
    tax_year = models.SmallIntegerField(null=True, blank=True)

    is_active = models.BooleanField(default=False)
    is_archived = models.BooleanField(default=False)
    preparer_email = models.CharField(max_length=254, blank=True, default="")

    expected_fee = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    discount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    expected_fee_at = models.DateTimeField(null=True, blank=True)

    source_invoice_id = models.UUIDField(null=True, blank=True, db_index=True)
    invoice_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    invoice_balance = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    invoice_paid_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    invoice_status = models.CharField(max_length=16, blank=True, default="")
    invoice_paid_at = models.DateTimeField(null=True, blank=True)

    actual_revenue_recognized = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    actual_paid_at = models.DateTimeField(null=True, blank=True)
    revenue_gap = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="expected_fee minus actual recognized (null if either side missing).",
    )
    days_to_payment = models.IntegerField(null=True, blank=True)

    clearing_complete_at = models.DateTimeField(null=True, blank=True)
    ready_for_review_at = models.DateTimeField(null=True, blank=True)
    filed_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    review_started_at = models.DateTimeField(null=True, blank=True)
    ack_count = models.PositiveSmallIntegerField(default=0)
    ack_accepted_count = models.PositiveSmallIntegerField(default=0)
    ack_rejected_count = models.PositiveSmallIntegerField(default=0)
    expected_ack_count = models.PositiveSmallIntegerField(null=True, blank=True)
    tp_comp_date = models.DateField(
        null=True,
        blank=True,
        help_text="Sunday after latest compensating ack (Pacific); computed on ETL sync.",
    )

    has_parser_snapshot = models.BooleanField(default=False)
    parser_federal_amount = models.CharField(max_length=64, blank=True, default="")
    parser_states = models.CharField(max_length=255, blank=True, default="")
    parser_tax_prep_fee = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    intake_created_at = models.DateTimeField(null=True, blank=True)
    etl_synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["tax_season_year", "lifecycle_state"]),
            models.Index(fields=["payment_method", "lifecycle_state"]),
        ]

    def __str__(self):
        return f"PA {self.source_pa_id} ({self.lifecycle_state})"


class FactInvoice(models.Model):
    source_invoice_id = models.UUIDField(unique=True)
    source_client_id = models.PositiveIntegerField(db_index=True)
    status = models.CharField(max_length=16, blank=True, default="")
    qbo_invoice_number = models.CharField(max_length=32, blank=True, default="")
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    is_paid = models.BooleanField(default=False)
    txn_date = models.DateField(null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(null=True, blank=True)
    last_activity_at = models.DateTimeField(null=True, blank=True, db_index=True)
    linked_pa_count = models.PositiveSmallIntegerField(default=0)
    etl_synced_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Invoice {self.source_invoice_id} ({self.status})"


class FactAck(models.Model):
    source_ack_id = models.PositiveIntegerField(unique=True)
    source_pa_id = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    source_client_id = models.PositiveIntegerField(null=True, blank=True)
    tax_season_year = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    form_type = models.CharField(max_length=32, blank=True, default="")
    ack_year = models.PositiveSmallIntegerField(null=True, blank=True)
    ack_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=32, blank=True, default="")
    client_name = models.CharField(max_length=128, blank=True, default="")
    client_tin = models.CharField(max_length=9, blank=True, default="")
    created_at = models.DateTimeField(null=True, blank=True)
    etl_synced_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Ack {self.source_ack_id} ({self.status})"


class AgentQueryAudit(models.Model):
    """Audit log for Track C agent SQL (analytics DB only)."""

    class Status(models.TextChoices):
        SUCCESS = "SUCCESS", "Success"
        FAILED = "FAILED", "Failed"

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    user_email = models.CharField(max_length=254, blank=True, default="")
    user_role = models.CharField(max_length=50, blank=True, default="")
    question = models.TextField(blank=True, default="")
    sql_hash = models.CharField(max_length=64, blank=True, default="", db_index=True)
    sql_text = models.TextField(blank=True, default="")
    row_count = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.SUCCESS)
    error_message = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Agent query {self.created_at:%Y-%m-%d %H:%M} ({self.status})"


class FactLifecycleEvent(models.Model):
    source_transition_id = models.PositiveIntegerField(unique=True)
    source_pa_id = models.PositiveIntegerField(db_index=True)
    tax_season_year = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    from_state = models.CharField(max_length=32, blank=True, default="")
    to_state = models.CharField(max_length=32, blank=True, default="", db_index=True)
    actor_email = models.CharField(max_length=254, blank=True, default="")
    created_at = models.DateTimeField(db_index=True)
    etl_synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at", "source_transition_id"]

    def __str__(self):
        return f"PA {self.source_pa_id}: {self.from_state} → {self.to_state}"
