"""Acknowledgment display and PA summary selectors (Phase 8)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from django.conf import settings
from django.utils import timezone
from zoneinfo import ZoneInfo

from core.models import AckStaging, Acknowledgment, LifecycleState, ProductAssignment
from core.utils import get_active_tax_season

from acknowledgments.services.form_taxonomy import ack_jurisdiction_bucket
from acknowledgments.services.reconcile import (
    is_accepted_status,
    is_rejected_status,
    is_compensating_ack_status,
)

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
    accepted = sum(1 for a in acks if is_compensating_ack_status(a.status))
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


def _sunday_after_pacific(landmark: date) -> date:
    """Sunday strictly after *landmark* on the Pacific calendar."""
    days_until_sunday = (6 - landmark.weekday()) % 7
    if days_until_sunday == 0:
        return landmark + timedelta(days=7)
    return landmark + timedelta(days=days_until_sunday)


def format_tp_comp_tooltip(comp_date: date) -> str:
    tz = ZoneInfo(getattr(settings, "FIRM_TIME_ZONE", "America/Los_Angeles"))
    dt = datetime.combine(comp_date, time(12, 0), tzinfo=tz)
    return f"{comp_date.isoformat()} {dt.strftime('%Z')}"


def _force_completion_landmark_date(pa: ProductAssignment) -> date | None:
    if not pa.force_completed_at:
        return None
    tz = ZoneInfo(getattr(settings, "FIRM_TIME_ZONE", "America/Los_Angeles"))
    return timezone.localtime(pa.force_completed_at, tz).date()


def compute_tp_comp_date(pa: ProductAssignment) -> date | None:
    """
    Proprietary compensation date: Sunday after latest compensating ack when all
    expected acks are A (paper-filed counts as A; force completion counts as A).
    """
    acks = list(pa.acknowledgments.all())
    force_date = _force_completion_landmark_date(pa)

    if force_date is not None:
        dates = [a.date for a in acks if a.date and is_compensating_ack_status(a.status)]
        dates.append(force_date)
        return _sunday_after_pacific(max(dates))

    expected = pa.expected_ack_count
    if not expected or expected < 1:
        return None

    if len(acks) < expected:
        return None

    if not all(is_compensating_ack_status(a.status) for a in acks):
        return None

    dates = [a.date for a in acks if a.date]
    if len(dates) != len(acks):
        return None

    return _sunday_after_pacific(max(dates))


def _review_status_label(pa: ProductAssignment) -> str:
    state = (pa.lifecycle_state or "").strip()
    labels = {
        LifecycleState.READY_FOR_REVIEW: "Ready",
        LifecycleState.IN_REVIEW: "In review",
        LifecycleState.FILED: "Pending acks",
        LifecycleState.ACK_RECONCILING: "Pending acks",
        LifecycleState.PENDING_REJECT_CORRECTION: "Reject",
        LifecycleState.CLOSED: "Filed",
    }
    return labels.get(state, "—")


def _bucket_acks(acks: list[Acknowledgment]) -> tuple[list[Acknowledgment], list[Acknowledgment]]:
    federal: list[Acknowledgment] = []
    state: list[Acknowledgment] = []
    for ack in acks:
        bucket = ack_jurisdiction_bucket(ack.type or "")
        if bucket == "federal":
            federal.append(ack)
        elif bucket == "state":
            state.append(ack)
    return federal, state


def _aggregate_ack_status(acks: list[Acknowledgment]) -> str:
    if not acks:
        return "—"
    if any(is_rejected_status(a.status) for a in acks):
        return Acknowledgment.STATUS_REJECTED
    if all(is_accepted_status(a.status) or is_compensating_ack_status(a.status) for a in acks):
        return Acknowledgment.STATUS_ACCEPTED
    accepted = sum(1 for a in acks if is_accepted_status(a.status) or is_compensating_ack_status(a.status))
    return f"{accepted}/{len(acks)}"


def _latest_ack_date(acks: list[Acknowledgment]) -> date | None:
    dates = [a.date for a in acks if a.date]
    return max(dates) if dates else None


def _format_ack_date(d: date | None, *, multi: bool = False) -> str:
    if multi:
        return "multi"
    return d.isoformat() if d else "—"


def _bucket_popover_lines(acks: list[Acknowledgment]) -> str:
    if not acks:
        return ""
    parts = []
    for ack in acks:
        dt = ack.date.isoformat() if ack.date else "—"
        parts.append(f"{ack.type or '—'} {ack.status or '—'} {dt}")
    return "\n".join(parts)


def _status_display(
    status: str,
    *,
    forced: bool,
) -> str:
    if forced and status == Acknowledgment.STATUS_REJECTED:
        return f"{status} (Forced)"
    return status


def build_clearing_status_columns(pa: ProductAssignment) -> dict:
    acks = list(pa.acknowledgments.all().order_by("date", "type"))
    federal_acks, state_acks = _bucket_acks(acks)
    forced = bool(pa.force_completed_at)

    fed_has_reject = any(is_rejected_status(a.status) for a in federal_acks)
    st_has_reject = any(is_rejected_status(a.status) for a in state_acks)

    fed_status = _status_display(
        _aggregate_ack_status(federal_acks),
        forced=forced and fed_has_reject,
    )
    st_status = _status_display(
        _aggregate_ack_status(state_acks),
        forced=forced and st_has_reject,
    )

    fed_dt = _format_ack_date(_latest_ack_date(federal_acks))
    state_dates = {a.date for a in state_acks if a.date}
    if len(state_dates) > 1:
        st_dt = _format_ack_date(None, multi=True)
    else:
        st_dt = _format_ack_date(_latest_ack_date(state_acks))

    tp_comp = compute_tp_comp_date(pa)
    tp_comp_display = tp_comp.isoformat() if tp_comp else "—"
    tp_comp_tooltip = format_tp_comp_tooltip(tp_comp) if tp_comp else ""

    ack_summary = build_pa_ack_summary(pa)

    return {
        "rev_status": _review_status_label(pa),
        "fed_status": fed_status,
        "st_status": st_status,
        "fed_dt": fed_dt,
        "st_dt": st_dt,
        "tp_comp_dt": tp_comp_display,
        "tp_comp_tooltip": tp_comp_tooltip,
        "fed_popover": _bucket_popover_lines(federal_acks),
        "st_popover": _bucket_popover_lines(state_acks),
        "ack_summary": ack_summary,
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
