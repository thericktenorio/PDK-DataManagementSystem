from django.conf import settings
from django.utils import timezone
from .models import Invoice


def minutes_since(dt) -> float:
    if not dt:
        return 10**9 # treat missing timestamps as very old
    return (timezone.now() - dt).total_seconds() / 60.0


def is_invoice_eligible_to_send(invoice : Invoice) -> bool:
    '''
    Quiet-period rule only (no signature gate yet).
    Eligible when invoice is Draft/Issued and quiet period has elapsed since last_activity_at.
    '''
    if invoice.status not in {Invoice.INVOICE_STATUS_DRAFT, Invoice.INVOICE_STATUS_ISSUED}:
        return False
    quiet = getattr(settings, "BILLING_QUIET_PERIOD_MINUTES", 5)
    return minutes_since(invoice.last_activity_at) >= quiet