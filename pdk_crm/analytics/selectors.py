"""
Read-only KPI queries against the analytics warehouse (never tax_operations).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from statistics import median

from django.conf import settings
from django.db.models import Count, Sum

from analytics.models import DimTaxSeason, EtlRun, FactAssignment
from core.models import LifecycleState


def warehouse_available() -> bool:
    return bool(getattr(settings, "ANALYTICS_ENABLED", False))


def _facts():
    return FactAssignment.objects.using("analytics")


@dataclass
class LifecycleBucket:
    label: str
    count: int


@dataclass
class SeasonKpiSnapshot:
    tax_season_year: int
    total_assignments: int
    clients_serviced: int
    lifecycle_buckets: list[LifecycleBucket] = field(default_factory=list)
    expected_revenue: Decimal = Decimal("0")
    recognized_revenue: Decimal = Decimal("0")
    revenue_gap: Decimal = Decimal("0")
    collection_rate_pct: float | None = None
    median_days_to_payment: int | None = None
    outstanding_expected: Decimal = Decimal("0")
    closed_count: int = 0
    in_progress_count: int = 0
    parser_assisted_count: int = 0


@dataclass
class AnalyticsDashboardContext:
    warehouse_enabled: bool
    last_etl_finished_at: object | None = None
    last_etl_status: str = ""
    seasons: list[dict] = field(default_factory=list)
    selected_season_year: int | None = None
    snapshot: SeasonKpiSnapshot | None = None
    error_message: str = ""


def get_last_successful_etl():
    if not warehouse_available():
        return None
    return (
        EtlRun.objects.using("analytics")
        .filter(status=EtlRun.Status.SUCCESS)
        .order_by("-finished_at")
        .first()
    )


def list_season_options() -> list[dict]:
    if not warehouse_available():
        return []
    seasons = DimTaxSeason.objects.using("analytics").order_by("-year")
    return [
        {
            "year": s.year,
            "is_active": s.is_active,
            "label": f"Tax season {s.year}" + (" (active)" if s.is_active else ""),
        }
        for s in seasons
    ]


def _default_season_year(seasons: list[dict]) -> int | None:
    if not seasons:
        return None
    for s in seasons:
        if s.get("is_active"):
            return s["year"]
    return seasons[0]["year"]


def _money(value) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value)).quantize(Decimal("0.01"))


LIFECYCLE_DISPLAY = (
    (LifecycleState.IN_CLEARING, "In clearing"),
    (LifecycleState.CLEARING_COMPLETE, "Clearing complete"),
    (LifecycleState.AWAITING_PAYMENT, "Awaiting payment"),
    (LifecycleState.READY_FOR_REVIEW, "Ready for review"),
    (LifecycleState.IN_REVIEW, "In review"),
    (LifecycleState.FILED, "Filed"),
    (LifecycleState.ACK_RECONCILING, "Ack reconciling"),
    (LifecycleState.PENDING_REJECT_CORRECTION, "Pending reject"),
    (LifecycleState.CLOSED, "Closed"),
)

OUTSTANDING_LIFECYCLE = {
    LifecycleState.CLEARING_COMPLETE,
    LifecycleState.AWAITING_PAYMENT,
}


def build_season_snapshot(tax_season_year: int) -> SeasonKpiSnapshot:
    qs = _facts().filter(tax_season_year=tax_season_year)
    total = qs.count()
    clients = qs.values("source_client_id").distinct().count()

    agg = qs.aggregate(
        expected=Sum("expected_fee"),
        recognized=Sum("actual_revenue_recognized"),
        gap=Sum("revenue_gap"),
    )
    expected = _money(agg["expected"])
    recognized = _money(agg["recognized"])
    gap = _money(agg["gap"])

    collection_rate = None
    if expected > 0:
        collection_rate = float((recognized / expected * Decimal("100")).quantize(Decimal("0.1")))

    days_list = [
        d
        for d in qs.exclude(days_to_payment__isnull=True).values_list("days_to_payment", flat=True)
        if d is not None
    ]
    med_days = int(median(days_list)) if days_list else None

    outstanding = _money(
        qs.filter(lifecycle_state__in=OUTSTANDING_LIFECYCLE).aggregate(s=Sum("expected_fee"))["s"]
    )

    closed_count = qs.filter(lifecycle_state=LifecycleState.CLOSED).count()
    parser_count = qs.filter(has_parser_snapshot=True).count()

    buckets: list[LifecycleBucket] = []
    counts_by_state = {
        row["lifecycle_state"]: row["c"]
        for row in qs.values("lifecycle_state").annotate(c=Count("id"))
    }
    for state, label in LIFECYCLE_DISPLAY:
        buckets.append(LifecycleBucket(label=label, count=counts_by_state.get(state, 0)))

    return SeasonKpiSnapshot(
        tax_season_year=tax_season_year,
        total_assignments=total,
        clients_serviced=clients,
        lifecycle_buckets=buckets,
        expected_revenue=expected,
        recognized_revenue=recognized,
        revenue_gap=gap,
        collection_rate_pct=collection_rate,
        median_days_to_payment=med_days,
        outstanding_expected=outstanding,
        closed_count=closed_count,
        in_progress_count=total - closed_count,
        parser_assisted_count=parser_count,
    )


def get_dashboard_context(*, season_year: int | None = None) -> AnalyticsDashboardContext:
    if not warehouse_available():
        return AnalyticsDashboardContext(
            warehouse_enabled=False,
            error_message="Analytics warehouse is not enabled in this environment.",
        )

    last_etl = get_last_successful_etl()
    seasons = list_season_options()
    selected = season_year or _default_season_year(seasons)

    ctx = AnalyticsDashboardContext(
        warehouse_enabled=True,
        last_etl_finished_at=last_etl.finished_at if last_etl else None,
        last_etl_status=last_etl.status if last_etl else "",
        seasons=seasons,
        selected_season_year=selected,
    )

    if not last_etl:
        ctx.error_message = "No successful ETL run yet. Run sync_analytics_warehouse."
        return ctx

    if selected is None:
        ctx.error_message = "No tax seasons in the warehouse. Run a full ETL sync."
        return ctx

    ctx.snapshot = build_season_snapshot(selected)
    return ctx
