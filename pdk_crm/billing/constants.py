from enum import Enum


class InvoiceCanonicalStatus(str, Enum):
    OPEN = "Open"
    PARTIAL = "Partial"
    PAID = "Paid"
    VOIDED = "Voided"
    CANCELED = "Canceled"   # e.g. deleted/archived upstream
    FAILED = "Failed"       # internal: reconciliation error