from core.models import LifecycleState, ProductAssignment
from core.utils import get_active_tax_season
from core.workflows.lifecycle import is_no_fee_payment_method, is_qbo_payment_method

from acknowledgments.selectors import build_pa_ack_summary
from acknowledgments.services.reconcile import is_rejected_status

from billing.models import Invoice
from billing.selectors import pa_billing_context

from clearing.services.parser_schema import suggested_expected_ack_count

from review.models import ReviewEntry
from review.services.queue import ensure_review_entry

REVIEW_BASE_STATES = frozenset({
    LifecycleState.READY_FOR_REVIEW,
    LifecycleState.FILED,
    LifecycleState.ACK_RECONCILING,
    LifecycleState.PENDING_REJECT_CORRECTION,
    LifecycleState.CLOSED,
    LifecycleState.IN_REVIEW,
})

REVIEW_TABLE_STATES = {
    "ready": (LifecycleState.READY_FOR_REVIEW,),
    "pending_acks": (LifecycleState.FILED, LifecycleState.ACK_RECONCILING),
    "pending_reject": (LifecycleState.PENDING_REJECT_CORRECTION,),
    "filed": (LifecycleState.CLOSED,),
}


def _review_base_queryset(*, tax_season=None):
    if tax_season is None:
        tax_season = get_active_tax_season()
    if tax_season is None:
        return ProductAssignment.objects.none()

    return (
        ProductAssignment.objects.filter(
            intake__tax_season=tax_season,
            is_active=True,
            lifecycle_state__in=REVIEW_BASE_STATES,
        )
        .select_related(
            "client",
            "product",
            "tax_year",
            "filing_type",
            "preparer",
            "intake__tax_season",
            "invoice_link__invoice",
        )
        .prefetch_related("acknowledgments", "review_entry")
        .order_by("client__name", "id")
    )


def review_table_queryset(*, table: str, tax_season=None):
    states = REVIEW_TABLE_STATES.get(table)
    if not states:
        return ProductAssignment.objects.none()
    return _review_base_queryset(tax_season=tax_season).filter(
        lifecycle_state__in=states
    )


def review_queue_queryset(*, tax_season=None):
    """All PAs visible across the four review tables."""
    return _review_base_queryset(tax_season=tax_season)


def review_queue_count(*, tax_season=None) -> int:
    return review_queue_queryset(tax_season=tax_season).count()


def payment_status_label(pa: ProductAssignment) -> str:
    billing = pa_billing_context(pa)
    inv_status = (billing.get("invoice_status") or "").strip()

    if inv_status == Invoice.INVOICE_STATUS_PAID:
        return "Paid"
    if billing.get("invoice_badge"):
        return billing["invoice_badge"]
    if is_no_fee_payment_method(pa):
        return "No fee"
    if not is_qbo_payment_method(pa):
        state = (pa.lifecycle_state or "").strip()
        if state in {
            LifecycleState.READY_FOR_REVIEW,
            LifecycleState.IN_REVIEW,
            LifecycleState.FILED,
            LifecycleState.ACK_RECONCILING,
            LifecycleState.CLOSED,
            LifecycleState.PENDING_REJECT_CORRECTION,
        }:
            return "Payment confirmed"
        return pa.get_payment_method_display() or "—"
    return inv_status or "—"


def _reviewer_display(entry: ReviewEntry | None) -> str:
    if not entry or not entry.assigned_reviewer_id:
        return "—"
    user = entry.assigned_reviewer
    name = f"{user.first_name} {user.last_name}".strip()
    return name or user.email


def _lifecycle_display_label(state: str) -> str:
    if state == LifecycleState.CLOSED:
        return "Filed"
    return dict(LifecycleState.choices).get(state, state)


def build_review_row(pa: ProductAssignment) -> dict:
    entry = getattr(pa, "review_entry", None)
    if entry is None:
        entry = ensure_review_entry(pa)

    state = pa.lifecycle_state or LifecycleState.READY_FOR_REVIEW
    billing = pa_billing_context(pa)
    preparer = pa.preparer
    preparer_label = "—"
    if preparer:
        preparer_label = f"{preparer.first_name} {preparer.last_name}".strip() or preparer.email

    ack_summary = build_pa_ack_summary(pa)
    has_reject_ack = any(
        is_rejected_status(a.status) for a in pa.acknowledgments.all()
    )
    can_force_complete = (
        state in {
            LifecycleState.PENDING_REJECT_CORRECTION,
            LifecycleState.FILED,
            LifecycleState.ACK_RECONCILING,
        }
        and (state == LifecycleState.PENDING_REJECT_CORRECTION or has_reject_ack)
    )
    can_paper_file = state in {
        LifecycleState.READY_FOR_REVIEW,
        LifecycleState.FILED,
        LifecycleState.ACK_RECONCILING,
        LifecycleState.PENDING_REJECT_CORRECTION,
    }

    return {
        "pa": pa,
        "pa_id": pa.id,
        "client_name": pa.client.name,
        "client_tin": pa.client.TIN,
        "product_type": pa.product.product_type if pa.product_id else "—",
        "tax_year": pa.tax_year.year if pa.tax_year_id else "—",
        "filing_type": pa.filing_type.filing_type if pa.filing_type_id else "—",
        "preparer": preparer_label,
        "fee": pa.fee,
        "payment_method": pa.get_payment_method_display() or "—",
        "payment_status": payment_status_label(pa),
        "invoice_status": billing.get("invoice_status") or "",
        "invoice_number": billing.get("qbo_invoice_number") or "",
        "lifecycle_state": state,
        "lifecycle_label": _lifecycle_display_label(state),
        "assigned_reviewer": _reviewer_display(entry),
        "notes": entry.notes,
        "review_started_at": entry.review_started_at,
        "ack_summary": ack_summary,
        "can_complete_review": state == LifecycleState.READY_FOR_REVIEW,
        "can_complete_reject_correction": state == LifecycleState.PENDING_REJECT_CORRECTION,
        "can_force_complete": can_force_complete,
        "can_paper_file": can_paper_file,
        "suggested_expected_ack_count": suggested_expected_ack_count(pa),
    }
