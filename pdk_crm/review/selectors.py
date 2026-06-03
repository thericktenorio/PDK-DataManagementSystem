from core.models import LifecycleState, ProductAssignment
from core.utils import get_active_tax_season
from core.workflows.lifecycle import is_no_fee_payment_method, is_qbo_payment_method

from billing.models import Invoice
from billing.selectors import pa_billing_context

from review.models import ReviewEntry
from review.services.queue import ensure_review_entry

REVIEW_QUEUE_STATES = (
    LifecycleState.READY_FOR_REVIEW,
    LifecycleState.IN_REVIEW,
)


def review_queue_queryset(*, tax_season=None):
    if tax_season is None:
        tax_season = get_active_tax_season()
    if tax_season is None:
        return ProductAssignment.objects.none()

    return (
        ProductAssignment.objects.filter(
            intake__tax_season=tax_season,
            is_active=True,
            lifecycle_state__in=REVIEW_QUEUE_STATES,
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
        .prefetch_related("review_entry")
        .order_by("lifecycle_state", "client__name", "id")
    )


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

    return {
        "pa": pa,
        "pa_id": pa.id,
        "client_name": pa.client.name,
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
        "lifecycle_label": dict(LifecycleState.choices).get(state, state),
        "assigned_reviewer": _reviewer_display(entry),
        "notes": entry.notes,
        "review_started_at": entry.review_started_at,
        "can_start": state == LifecycleState.READY_FOR_REVIEW,
        "can_mark_filed": state == LifecycleState.IN_REVIEW,
    }
