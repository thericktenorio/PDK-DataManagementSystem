"""Acknowledgment display and PA summary selectors (Phase 8)."""

from core.models import AckStaging, Acknowledgment, LifecycleState, ProductAssignment
from core.utils import get_active_tax_season

from acknowledgments.services.reconcile import is_accepted_status, is_rejected_status

ACK_POST_FILING_STATES = frozenset({
    LifecycleState.FILED,
    LifecycleState.ACK_RECONCILING,
    LifecycleState.PENDING_REJECT_CORRECTION,
    LifecycleState.CLOSED,
})


def _ack_status_css(status: str) -> str:
    if is_accepted_status(status):
        return "ack-status-accepted"
    if is_rejected_status(status):
        return "ack-status-rejected"
    return "ack-status-pending"


def build_pa_ack_summary(pa: ProductAssignment) -> dict:
    acks = list(pa.acknowledgments.all().order_by("date", "type"))
    expected = pa.expected_ack_count
    received = len(acks)
    accepted = sum(1 for a in acks if is_accepted_status(a.status))
    rejected = sum(1 for a in acks if is_rejected_status(a.status))

    if rejected:
        badge_class = "ack-badge-rejected"
        badge_text = f"{accepted}/{expected or '?'} · reject"
    elif expected and received >= expected and accepted == received:
        badge_class = "ack-badge-complete"
        badge_text = f"{accepted}/{expected} ✓"
    elif received:
        badge_class = "ack-badge-progress"
        badge_text = f"{accepted}/{expected or '?'}"
    else:
        badge_class = "ack-badge-none"
        badge_text = f"0/{expected}" if expected else "—"

    return {
        "expected_count": expected,
        "received_count": received,
        "accepted_count": accepted,
        "rejected_count": rejected,
        "badge_text": badge_text,
        "badge_class": badge_class,
        "show_badge": bool(
            expected
            or received
            or (pa.lifecycle_state or "") in ACK_POST_FILING_STATES
        ),
        "acks": [
            {
                "type": a.type or "—",
                "status": a.status or "—",
                "date": a.date.isoformat() if a.date else "",
                "status_class": _ack_status_css(a.status),
            }
            for a in acks
        ],
    }


def build_pa_ack_summaries(pa_ids: list[int]) -> dict[int, dict]:
    if not pa_ids:
        return {}
    pas = (
        ProductAssignment.objects.filter(id__in=pa_ids)
        .prefetch_related("acknowledgments")
    )
    return {pa.id: build_pa_ack_summary(pa) for pa in pas}


def pending_unmatched_staging(*, tax_season=None) -> list[dict]:
    if tax_season is None:
        tax_season = get_active_tax_season()
    if tax_season is None:
        return []

    rows = AckStaging.objects.filter(
        match_state__in={
            AckStaging.MATCH_UNMATCHED,
            AckStaging.MATCH_AMBIGUOUS,
            AckStaging.MATCH_NEEDS_FILING_TYPE,
            AckStaging.MATCH_CLIENT_NOT_FOUND,
        },
        suggested_tax_season_year=tax_season.year,
    ).order_by("-created_at")[:200]

    return [
        {
            "id": st.id,
            "tin": st.client_tin or "—",
            "form_type": st.type or "—",
            "client_name": st.client_name or "—",
            "status": st.status or "—",
            "reason": st.reason or "",
            "match_state": st.match_state,
        }
        for st in rows
    ]


def acknowledgments_for_display(*, tax_season_year: int):
    return (
        Acknowledgment.objects.filter(tax_season__year=tax_season_year)
        .select_related("product_assignment")
        .order_by("-date", "-created_at")
    )
