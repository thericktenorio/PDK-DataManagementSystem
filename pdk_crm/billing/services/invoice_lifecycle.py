"""
Phase 6: lifecycle transitions driven by invoice send / paid events.
"""
from __future__ import annotations

import logging

from core.models import LifecycleState, ProductAssignment
from core.workflows.lifecycle import (
    cmd_mark_awaiting_payment,
    cmd_mark_ready_for_review,
    is_qbo_payment_method,
)

from billing.models import Invoice

logger = logging.getLogger(__name__)

SENT_INVOICE_STATUSES = frozenset({
    Invoice.INVOICE_STATUS_SENT,
    Invoice.INVOICE_STATUS_PARTIAL,
    Invoice.INVOICE_STATUS_PAID,
})


def invoice_is_sent(invoice: Invoice) -> bool:
    if invoice.status in SENT_INVOICE_STATUSES:
        return True
    return bool(invoice.qbo_invoice_id) and invoice.status != Invoice.INVOICE_STATUS_DRAFT


def advance_pas_when_invoice_sent(invoice: Invoice, pas, *, actor=None) -> int:
    """QBO PAs in CLEARING_COMPLETE → AWAITING_PAYMENT after invoice is sent."""
    advanced = 0
    for pa in pas:
        if not isinstance(pa, ProductAssignment):
            pa = ProductAssignment.objects.get(pk=pa)
        pa.refresh_from_db()
        state = (pa.lifecycle_state or "").strip()
        if state != LifecycleState.CLEARING_COMPLETE:
            continue
        if not is_qbo_payment_method(pa):
            continue
        cmd_mark_awaiting_payment(pa_id=pa.id, actor=actor)
        advanced += 1
    if advanced:
        logger.info("Invoice %s sent: %s PA(s) → AWAITING_PAYMENT", invoice.id, advanced)
    return advanced


def advance_pas_when_invoice_paid(invoice: Invoice, *, actor=None) -> int:
    """Linked PAs in AWAITING_PAYMENT → READY_FOR_REVIEW when invoice is fully paid."""
    if not invoice.is_paid:
        return 0

    advanced = 0
    for link in invoice.assignment_links.select_related("product_assignment"):
        pa = link.product_assignment
        state = (pa.lifecycle_state or "").strip()
        if state != LifecycleState.AWAITING_PAYMENT:
            continue
        cmd_mark_ready_for_review(pa_id=pa.id, actor=actor)
        advanced += 1

    if advanced:
        logger.info("Invoice %s paid: %s PA(s) → READY_FOR_REVIEW", invoice.id, advanced)
    return advanced
