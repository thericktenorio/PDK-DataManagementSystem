"""
Phase 6: billing hooks after clearing completes (replaces is_complete signal).
"""
from __future__ import annotations

from core.models import ProductAssignment
from core.workflows.lifecycle import (
    cmd_mark_ready_for_review,
    is_no_fee_payment_method,
    is_qbo_payment_method,
)

from billing.services.drafts import get_or_create_draft_invoice, link_pas_to_draft


def on_clearing_completed(*, pa_id: int, actor=None) -> ProductAssignment:
    """
    After cmd_complete_clearing:
    - No-fee → READY_FOR_REVIEW immediately
    - QBO → link to client draft invoice; stay CLEARING_COMPLETE until send
    - Other non-QBO → stay CLEARING_COMPLETE until staff confirms payment
    """
    pa = ProductAssignment.objects.select_related("client").get(pk=pa_id)

    if is_no_fee_payment_method(pa):
        return cmd_mark_ready_for_review(pa_id=pa_id, actor=actor)

    if is_qbo_payment_method(pa):
        invoice = get_or_create_draft_invoice(pa.client, tax_year=None)
        link_pas_to_draft(invoice, [pa])
        pa.refresh_from_db()
        return pa

    return pa
