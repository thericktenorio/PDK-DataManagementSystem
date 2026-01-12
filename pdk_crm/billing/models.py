from django.db import models
from django.utils import timezone
from django.conf import settings

import uuid
import hashlib


class QboConnection(models.Model):
    org = models.OneToOneField("core.Organization", on_delete = models.CASCADE)

    realm_id = models.CharField(max_length = 32, unique = True)
    access_token = models.TextField()
    refresh_token = models.TextField()
    access_token_expires_at = models.DateTimeField()
    is_active = models.BooleanField(default = True)

    def token_expires_soon(self, skew_seconds: int = 120) -> bool:
        return timezone.now() >= (self.access_token_expires_at - timezone.timedelta(seconds = skew_seconds))
    
    def __str__(self):
        return f"QBO({self.org}) [{self.realm_id}]"


class DeliveryStatus(models.TextChoices):
    RECEIVED = "received", "Received"
    PROCESSED = "processed", "Processed"
    ERROR = "error", "Error"


class EventStatus(models.TextChoices):
    RECEIVED = "received", "Received"
    QUEUED = "queued", "Queued"
    PROCESSED = "processed", "Processed"
    ERROR = "error", "Error"


class QboWebhookDelivery(models.Model):
    ''' 
    one row per HTTP POST from Intuit
    deduped by event_hash (sha256 of raw_body)
    '''
    id = models.UUIDField(primary_key = True, default = uuid.uuid4, editable = False)
    received_at = models.DateTimeField(auto_now_add = True)
    intuit_signature = models.CharField(max_length = 255, blank = True)
    realm_id = models.CharField(max_length = 32, blank = True)
    raw_body = models.TextField()   # exact request body as bytes -> str
    json_payload = models.JSONField()   # parsed JSON for convenience
    event_hash = models.CharField(max_length = 64, unique = True)   # sha256 hex of raw_body
    status = models.CharField(max_length = 20, choices = DeliveryStatus.choices, default = DeliveryStatus.RECEIVED)
    error_message = models.TextField(blank = True)

    class Meta:
        indexes = [
            models.Index(fields = ["received_at"]),
            models.Index(fields = ["realm_id"]),
            models.Index(fields = ["status"]),
        ]
    
    @staticmethod
    def compute_hash(raw_body: bytes) -> str:
        return hashlib.sha256(raw_body).hexdigest()
    
    def __str__(self):
        return f"Delivery {self.received_at:%Y-%m-%d %H:%M:%S} realm = {self.realm_id} status = {self.status}"


class QboEntityEvent(models.Model):
    '''
    one row per entity referenced inside a delivery.
    idempotency enforced by unique constraint on (realm_id, entity_name, entity_id, operation, last_updated).
    '''
    id = models.UUIDField(primary_key = True, default = uuid.uuid4, editable = False)
    delivery = models.ForeignKey(QboWebhookDelivery, on_delete = models.CASCADE, related_name = "entity_events")
    realm_id = models.CharField(max_length = 32)
    entity_name = models.CharField(max_length = 32) # eg 'invoice', 'payment', 'client'
    entity_id = models.CharField(max_length = 64)   # qbo entity id as str
    operation = models.CharField(max_length = 32)   # eg 'create', 'update', 'delete'
    last_updated = models.DateTimeField()           # parsed from payload
    event_hash = models.CharField(max_length = 64, unique = True)   #sha256 of normalized tuple
    status = models.CharField(max_length = 20, choices = EventStatus.choices, default = EventStatus.RECEIVED)
    processed_at = models.DateTimeField(null = True, blank = True)
    error_message = models.TextField(blank = True)
    retries = models.PositiveIntegerField(default = 0)

    class Meta:
        unique_together = ("realm_id", "entity_name", "entity_id", "operation", "last_updated")
        indexes = [
            models.Index(fields = ["realm_id", "entity_name"]), 
            models.Index(fields = ["status"]), 
            models.Index(fields = ["last_updated"]),
            ]
    
    @staticmethod
    def compute_event_hash(realm_id: str, entity_name: str, entity_id: str, operation: str, last_updated_iso: str) -> str:
        key = f"{realm_id}:{entity_name}:{entity_id}:{operation}:{last_updated_iso}"
        return hashlib.sha256(key.encode("utf-8")).hexdigest()
    
    def __str__(self):
        return f"{self.entity_name} {self.operation} #{self.entity_id} @ {self.last_updated:%Y-%m-%d %H:%M:%S} ({self.status})"


# NOTE: this model links a client to a Qbo connection
class ClientQboLink(models.Model):
    client = models.OneToOneField("core.Client", on_delete = models.CASCADE, related_name = "qbo_link")
    realm_id = models.CharField(max_length = 32)
    qbo_customer_id = models.CharField(max_length = 64, unique = True)

    class Meta:
        unique_together = ("realm_id", "qbo_customer_id")
        indexes = [models.Index(fields = ["realm_id", "qbo_customer_id"])]


class Invoice(models.Model):
    INVOICE_STATUS_DRAFT = "Draft"
    INVOICE_STATUS_ISSUED = "Issued"
    INVOICE_STATUS_SENT = "Sent"
    INVOICE_STATUS_PAID = "Paid"
    INVOICE_STATUS_PARTIAL = "Partial"
    INVOICE_STATUS_VOIDED = "Voided"        # still present in QBO, amount set to 0
    INVOICE_STATUS_FAILED = "Failed"
    INVOICE_STATUS_DELETED = "Deleted"      # deleted from record
    INVOICE_STATUS_UNKNOWN = "Unknown"
    INVOICE_STATUS_CHOICES = [
        (INVOICE_STATUS_DRAFT, "Draft"),
        (INVOICE_STATUS_ISSUED, "Issued"),
        (INVOICE_STATUS_SENT, "Sent"),
        (INVOICE_STATUS_PAID, "Paid"),
        (INVOICE_STATUS_PARTIAL, "Partial"),
        (INVOICE_STATUS_VOIDED, "Voided"),      # still in QBO, amount set to 0
        (INVOICE_STATUS_FAILED, "Failed"),
        (INVOICE_STATUS_DELETED, "Deleted"),    # deleted from record
        (INVOICE_STATUS_UNKNOWN, "Unknown"),
    ]
    
    # Internal attributes
    id = models.UUIDField(primary_key = True, default = uuid.uuid4, editable = False)   # NOTE: internal unique ID
    client = models.ForeignKey("core.Client", on_delete = models.PROTECT, related_name = "invoices")    #NOTE: associates the invoice w/ an internal client
    status = models.CharField(max_length = 16, choices = INVOICE_STATUS_CHOICES, default = INVOICE_STATUS_DRAFT)
    created_at = models.DateTimeField(auto_now_add = True)  # when invoice was created internally
    updated_at = models.DateTimeField(auto_now = True)
    last_synced_at = models.DateTimeField(null = True, blank = True)

    last_activity_at = models.DateTimeField(default = timezone.now, db_index = True) # used to 
    
    @property
    def is_paid(self) -> bool:
        return self.qbo_amount_cents > 0 and self.qbo_balance_cents <= 0
    
    @property
    def is_partial(self) -> bool:
        return (self.status == self.INVOICE_STATUS_PARTIAL or (self.qbo_amount_cents > 0 and 0 < self.qbo_balance_cents < self.qbo_amount_cents))
    
    @property
    def is_open(self) -> bool:
        if self.status in {self.INVOICE_STATUS_VOIDED, self.INVOICE_STATUS_DELETED}:
            return False
        return(self.status in {self.INVOICE_STATUS_DRAFT, self.INVOICE_STATUS_ISSUED, self.INVOICE_STATUS_SENT} or (self.qbo_amount_cents > 0 and self.qbo_balance_cents == self.qbo_amount_cents))
    
    @property
    def is_voided(self) -> bool:
        return self.status == self.INVOICE_STATUS_VOIDED


    # QBO derived attributes
    qbo_invoice_id = models.CharField(max_length = 64, unique = True, null = True, blank = True) # NOTE: maps to QBO's Invoice.Id
    qbo_customer_id = models.CharField(max_length = 64, null = True, blank = True) # NOTE: maps to QBO's Customer.Id
    qbo_sync_token = models.CharField(max_length = 16, blank = True)    # QBO 'SyncToken'; required by QBO to update invoice
    qbo_last_updated = models.DateTimeField(null = True, blank = True)
    qbo_invoice_number = models.CharField(max_length = 32, blank = True)    # NOTE: QBO defined 'DocNumber' // restrain so invoice_number is mirrored from QBO
    qbo_amount_cents = models.BigIntegerField(default = 0)     # mirrors QBO TotalAmt, mitigates float rounding
    qbo_balance_cents = models.BigIntegerField(default = 0)     # mirrors QBO Balance
    qbo_currency = models.CharField(max_length = 8, default = "USD")    # NOTE: allows for multiple currency in the future
    qbo_txn_date = models.DateField(null = True, blank = True)      # txn_date is transaction date
    qbo_due_date = models.DateField(null = True, blank = True)
    
    last_qbo_payload = models.JSONField(null = True, blank = True)  # optional but very useful for support/observability

    class Meta:
        indexes = [
            models.Index(fields = ["qbo_invoice_id"]),
            models.Index(fields = ["qbo_invoice_number"]),
            models.Index(fields = ["qbo_customer_id"]),
            models.Index(fields = ["client"]),
            models.Index(fields = ["status"]),
            models.Index(fields = ["last_synced_at"]),
            models.Index(fields = ["qbo_last_updated"]),
            models.Index(fields = ["qbo_txn_date"]),
            models.Index(fields = ["qbo_due_date"]),
            models.Index(fields = ["client", "status"]),    # ability to list invoices by client & status
            models.Index(fields = ["last_activity_at"]),
        ]
        constraints = [
            models.CheckConstraint(check = models.Q(qbo_amount_cents__gte = 0), name = "invoice_amount_nonnegative"),
            models.CheckConstraint(check = models.Q(qbo_balance_cents__gte = 0), name = "invoice_balance_nonnegative"),
            models.CheckConstraint(check = models.Q(qbo_balance_cents__lte = models.F("qbo_amount_cents")), name = "invoice_balance_lte_amount",),      # balance <= amount
        ]    
    
    def __str__(self):
        label = self.qbo_invoice_number or self.qbo_invoice_id or str(self.id)
        return f"Invoice {label} - ({self.status})"

    # centralized updater for reconcile step (Phase 4)
    def apply_qbo_snapshot(self, qbo_invoice: dict, *, status: str | None = None) -> None:
        '''
        Update fields from an authoritative QBO Invoice payload.
        Use within a transaction in your reconcile service.
        '''
        if not isinstance(qbo_invoice, dict):
            return
        
        # common keys (defensive access)
        self.qbo_invoice_id = str(qbo_invoice.get("Id") or self.qbo_invoice_id or "")
        self.qbo_sync_token = str(qbo_invoice.get("SyncToken") or self.qbo_sync_token or "")
        self.qbo_invoice_number = str(qbo_invoice.get("DocNumber") or self.qbo_invoice_number or "")
        self.qbo_currency = (qbo_invoice.get("CurrencyRef", {}).get("value") or self.qbo_currency or "USD")

        # money (to cents) - upstream mapping should have already converted, but guard here too
        total_amt = qbo_invoice.get("TotalAmt")
        balance_amt = qbo_invoice.get("Balance")
        if total_amt is not None:
            self.qbo_amount_cents = int(round(float(total_amt) * 100))
        if balance_amt is not None:
            self.qbo_balance_cents = int(round(float(balance_amt) * 100))
        
        # dates (QBO returns ISO YYYY-MM-DD strings)
        if qbo_invoice.get("TxnDate"):
            self.qbo_txn_date = qbo_invoice["TxnDate"]
        if qbo_invoice.get("DueDate"):
            self.qbo_due_date = qbo_invoice["DueDate"]
        

        if status:
            self.status = status

        # keep last payload for support/audit
        self.last_qbo_payload = qbo_invoice


# LINK  BETWEEN PRODUCT ASSIGNMENT AND INVOICE
class AssignmentInvoiceLink(models.Model):
    '''
    Idempotency link: guarantees each ProductAssignment (PA) contributes to at most one invoice (one line) once.
    '''

    product_assignment = models.OneToOneField("core.ProductAssignment", on_delete = models.CASCADE, related_name = "invoice_link",)
    invoice = models.ForeignKey("billing.Invoice", on_delete = models.PROTECT, related_name = "assignment_links",)
    created_at = models.DateTimeField(auto_now_add = True)

    class Meta:
        indexes = [
            models.Index(fields = ["invoice"]),
            models.Index(fields = ["product_assignment"]),
        ]
    
    def __str__(self) -> str:
        return f"{self.product_assignment_id} -> {self.invoice_id}"