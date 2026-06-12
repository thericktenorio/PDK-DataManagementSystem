"""
Incremental ETL: tax_operations (default DB) → analytics warehouse.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from decimal import Decimal
from typing import Any
from django.conf import settings
from django.db import transaction
from django.db.models import Count, Max, Q
from django.utils import timezone

from analytics.models import (
    DimClient,
    DimProduct,
    DimTaxSeason,
    EtlRun,
    EtlWatermark,
    FactAck,
    FactAssignment,
    FactInvoice,
    FactLifecycleEvent,
)
from billing.models import AssignmentInvoiceLink, Invoice
from acknowledgments.selectors import compute_tp_comp_date
from core.models import (
    Acknowledgment,
    Client,
    LifecycleState,
    LifecycleTransition,
    Product,
    ProductAssignment,
    TaxSeason,
)
from review.models import ReviewEntry

logger = logging.getLogger(__name__)

WATERMARK_TRANSITIONS = "lifecycle_transitions"
WATERMARK_INVOICES = "invoices"
WATERMARK_ACKS = "acknowledgments"

QBO_PAYMENT = ProductAssignment.PAYMENT_METHOD_QBO
ALWAYS_PAID_METHODS = frozenset({
    ProductAssignment.PAYMENT_METHOD_CASH,
    ProductAssignment.PAYMENT_METHOD_CHECK,
    ProductAssignment.PAYMENT_METHOD_NO_FEE_DEPENDENT,
    ProductAssignment.PAYMENT_METHOD_NO_FEE_PRO_BONO,
    ProductAssignment.PAYMENT_METHOD_OTHER_APPLICATION,
    ProductAssignment.PAYMENT_METHOD_SQUARE,
    ProductAssignment.PAYMENT_METHOD_TPG,
})


def analytics_enabled() -> bool:
    return bool(getattr(settings, "ANALYTICS_ENABLED", False))


def _get_watermark(entity: str) -> EtlWatermark:
    wm, _ = EtlWatermark.objects.using("analytics").get_or_create(entity=entity)
    return wm


def _set_watermark(entity: str, *, last_int_id: int | None = None, last_datetime=None) -> None:
    wm = _get_watermark(entity)
    if last_int_id is not None:
        wm.last_int_id = last_int_id
    if last_datetime is not None:
        wm.last_datetime = last_datetime
    wm.save(using="analytics")


def _cents_to_decimal(cents: int | None) -> Decimal | None:
    if cents is None:
        return None
    return (Decimal(cents) / Decimal("100")).quantize(Decimal("0.01"))


def _parse_snapshot_fields(parse_result_json: dict | None) -> dict[str, Any]:
    if not parse_result_json or not isinstance(parse_result_json, dict):
        return {
            "has_parser_snapshot": False,
            "parser_federal_amount": "",
            "parser_states": "",
            "parser_tax_prep_fee": None,
        }
    fields = parse_result_json.get("fields") or {}
    if not isinstance(fields, dict):
        fields = {}
    fee_raw = fields.get("tax_prep_fee")
    parser_fee = None
    if fee_raw is not None and str(fee_raw).strip() != "":
        try:
            parser_fee = Decimal(str(fee_raw)).quantize(Decimal("0.01"))
        except Exception:
            parser_fee = None
    states = fields.get("states")
    return {
        "has_parser_snapshot": True,
        "parser_federal_amount": str(fields.get("federal_amount") or "")[:64],
        "parser_states": str(states or "")[:255],
        "parser_tax_prep_fee": parser_fee,
    }


def _transition_times(pa_id: int) -> dict[str, Any]:
    rows = LifecycleTransition.objects.filter(product_assignment_id=pa_id).order_by("created_at", "id")
    out: dict[str, Any] = {}
    for tr in rows:
        to_state = (tr.to_state or "").strip()
        if to_state == LifecycleState.CLEARING_COMPLETE and "clearing_complete_at" not in out:
            out["clearing_complete_at"] = tr.created_at
        elif to_state == LifecycleState.READY_FOR_REVIEW and "ready_for_review_at" not in out:
            out["ready_for_review_at"] = tr.created_at
        elif to_state == LifecycleState.FILED and "filed_at" not in out:
            out["filed_at"] = tr.created_at
        elif to_state == LifecycleState.CLOSED and "closed_at" not in out:
            out["closed_at"] = tr.created_at
    return out


def _resolve_revenue(
    *,
    payment_method: str,
    expected_fee: Decimal | None,
    expected_fee_at,
    clearing_complete_at,
    ready_for_review_at,
    invoice: Invoice | None,
) -> tuple[Decimal | None, Any, Decimal | None]:
    """
    Returns (actual_revenue_recognized, actual_paid_at, revenue_gap).
    """
    pm = (payment_method or "").strip()
    actual: Decimal | None = None
    paid_at = None

    if pm == QBO_PAYMENT and invoice:
        amount = _cents_to_decimal(invoice.qbo_amount_cents) or Decimal("0")
        balance = _cents_to_decimal(invoice.qbo_balance_cents) or Decimal("0")
        if invoice.is_paid:
            actual = amount
            paid_at = invoice.last_activity_at or invoice.updated_at
        elif invoice.qbo_amount_cents > 0:
            actual = (amount - balance).quantize(Decimal("0.01"))
            if actual > 0:
                paid_at = invoice.last_activity_at
    elif pm in ALWAYS_PAID_METHODS:
        if clearing_complete_at or ready_for_review_at:
            actual = expected_fee
            paid_at = ready_for_review_at or clearing_complete_at or expected_fee_at
    elif expected_fee is not None and (ready_for_review_at or clearing_complete_at):
        # Non-QBO methods that still advance to review without an invoice row
        actual = expected_fee
        paid_at = ready_for_review_at or clearing_complete_at or expected_fee_at

    gap = None
    if expected_fee is not None and actual is not None:
        gap = (expected_fee - actual).quantize(Decimal("0.01"))

    return actual, paid_at, gap


def _days_to_payment(expected_fee_at, actual_paid_at) -> int | None:
    if not expected_fee_at or not actual_paid_at:
        return None
    delta = actual_paid_at - expected_fee_at
    return max(0, int(delta.total_seconds() // 86400))


def sync_dimensions() -> int:
    count = 0
    for season in TaxSeason.objects.all():
        DimTaxSeason.objects.using("analytics").update_or_create(
            source_tax_season_id=season.id,
            defaults={
                "year": season.year,
                "start_date": season.start_date,
                "end_date": season.end_date,
                "is_active": season.is_active,
                "is_archived": season.is_archived,
            },
        )
        count += 1

    for client in Client.objects.all():
        DimClient.objects.using("analytics").update_or_create(
            source_client_id=client.id,
            defaults={
                "name": client.name or "",
                "tin": client.TIN or "",
                "email": client.email or "",
                "phone": client.phone or "",
                "filing_type": client.filing_type or "",
                "prior_filing_type": client.prior_filing_type or "",
                "appointment_type": client.appointment_type or "",
                "client_created_at": client.created_at,
            },
        )
        count += 1

    for product in Product.objects.select_related("tax_year").all():
        DimProduct.objects.using("analytics").update_or_create(
            source_product_id=product.id,
            defaults={
                "product_type": product.product_type or "",
                "tax_year": product.tax_year.year if product.tax_year_id else None,
                "default_price": product.default_price,
            },
        )
        count += 1

    return count


def sync_lifecycle_events(*, full: bool = False) -> tuple[int, int]:
    wm = _get_watermark(WATERMARK_TRANSITIONS)
    qs = LifecycleTransition.objects.select_related(
        "product_assignment__intake__tax_season",
        "actor",
    ).order_by("id")
    if not full and wm.last_int_id:
        qs = qs.filter(id__gt=wm.last_int_id)

    max_id = wm.last_int_id or 0
    count = 0
    for tr in qs.iterator(chunk_size=500):
        pa = tr.product_assignment
        season_year = None
        if pa and pa.intake_id:
            season_year = pa.intake.tax_season.year
        FactLifecycleEvent.objects.using("analytics").update_or_create(
            source_transition_id=tr.id,
            defaults={
                "source_pa_id": tr.product_assignment_id,
                "tax_season_year": season_year,
                "from_state": tr.from_state or "",
                "to_state": tr.to_state or "",
                "actor_email": (tr.actor.email if tr.actor_id else "") or "",
                "created_at": tr.created_at,
            },
        )
        max_id = max(max_id, tr.id)
        count += 1

    if count or full:
        _set_watermark(WATERMARK_TRANSITIONS, last_int_id=max_id)
    return count, max_id


def _collect_pa_ids_for_incremental() -> set[int]:
    wm_tr = _get_watermark(WATERMARK_TRANSITIONS)
    wm_inv = _get_watermark(WATERMARK_INVOICES)
    wm_ack = _get_watermark(WATERMARK_ACKS)

    pa_ids: set[int] = set()

    if wm_tr.last_int_id:
        pa_ids.update(
            LifecycleTransition.objects.filter(id__gt=wm_tr.last_int_id).values_list(
                "product_assignment_id", flat=True
            )
        )

    if wm_inv.last_datetime:
        inv_ids = Invoice.objects.filter(last_activity_at__gt=wm_inv.last_datetime).values_list(
            "id", flat=True
        )
        pa_ids.update(
            AssignmentInvoiceLink.objects.filter(invoice_id__in=inv_ids).values_list(
                "product_assignment_id", flat=True
            )
        )

    if wm_ack.last_int_id:
        pa_ids.update(
            Acknowledgment.objects.filter(id__gt=wm_ack.last_int_id)
            .exclude(product_assignment_id__isnull=True)
            .values_list("product_assignment_id", flat=True)
        )

    review_cutoff = wm_tr.last_datetime or (timezone.now() - timedelta(days=1))
    pa_ids.update(
        ReviewEntry.objects.filter(updated_at__gt=review_cutoff).values_list(
            "product_assignment_id", flat=True
        )
    )

    active_season_ids = list(TaxSeason.objects.filter(is_active=True).values_list("id", flat=True))
    if active_season_ids:
        pa_ids.update(
            ProductAssignment.objects.filter(intake__tax_season_id__in=active_season_ids).values_list(
                "id", flat=True
            )
        )

    return pa_ids


def _ack_agg(pa_id: int) -> dict[str, int]:
    qs = Acknowledgment.objects.filter(product_assignment_id=pa_id)
    total = qs.count()
    accepted = qs.filter(status=Acknowledgment.STATUS_ACCEPTED).count()
    rejected = qs.filter(status=Acknowledgment.STATUS_REJECTED).count()
    return {
        "ack_count": total,
        "ack_accepted_count": accepted,
        "ack_rejected_count": rejected,
    }


def _build_assignment_row(pa: ProductAssignment) -> dict[str, Any]:
    intake = pa.intake
    tax_season_year = intake.tax_season.year if intake else None
    transitions = _transition_times(pa.id)
    clearing_complete_at = transitions.get("clearing_complete_at")
    expected_fee_at = clearing_complete_at

    invoice = None
    link = (
        AssignmentInvoiceLink.objects.filter(product_assignment_id=pa.id)
        .select_related("invoice")
        .first()
    )
    if link:
        invoice = link.invoice

    invoice_amount = None
    invoice_balance = None
    invoice_paid_amount = None
    invoice_status = ""
    invoice_paid_at = None
    source_invoice_id = None

    if invoice:
        source_invoice_id = invoice.id
        invoice_amount = _cents_to_decimal(invoice.qbo_amount_cents)
        invoice_balance = _cents_to_decimal(invoice.qbo_balance_cents)
        invoice_status = invoice.status or ""
        if invoice.qbo_amount_cents and invoice.qbo_balance_cents is not None:
            paid_cents = max(0, invoice.qbo_amount_cents - invoice.qbo_balance_cents)
            invoice_paid_amount = _cents_to_decimal(paid_cents)
        if invoice.is_paid:
            invoice_paid_at = invoice.last_activity_at or invoice.updated_at

    expected_fee = pa.fee
    actual, actual_paid_at, gap = _resolve_revenue(
        payment_method=pa.payment_method or "",
        expected_fee=expected_fee,
        expected_fee_at=expected_fee_at,
        clearing_complete_at=clearing_complete_at,
        ready_for_review_at=transitions.get("ready_for_review_at"),
        invoice=invoice,
    )

    review = ReviewEntry.objects.filter(product_assignment_id=pa.id).first()
    filing_type_label = ""
    if pa.filing_type_id:
        filing_type_label = pa.filing_type.filing_type or ""

    preparer_email = ""
    if pa.preparer_id:
        preparer_email = pa.preparer.email or ""

    snapshot = _parse_snapshot_fields(pa.parse_result_json)
    acks = _ack_agg(pa.id)

    return {
        "source_pa_id": pa.id,
        "source_client_id": pa.client_id,
        "tax_season_year": tax_season_year or 0,
        "source_product_id": pa.product_id,
        "source_intake_id": pa.intake_id,
        "lifecycle_state": pa.lifecycle_state or "",
        "payment_method": pa.payment_method or "",
        "product_type": pa.product.product_type if pa.product_id else "",
        "filing_type": filing_type_label,
        "tax_year": pa.tax_year.year if pa.tax_year_id else None,
        "is_active": pa.is_active,
        "is_archived": pa.is_archived,
        "voided_at": pa.voided_at,
        "cancelled_at": pa.cancelled_at,
        "cancellation_reason": (pa.cancellation_reason or "")[:2000],
        "preparer_email": preparer_email,
        "expected_fee": expected_fee,
        "discount": pa.discount,
        "expected_fee_at": expected_fee_at,
        "source_invoice_id": source_invoice_id,
        "invoice_amount": invoice_amount,
        "invoice_balance": invoice_balance,
        "invoice_paid_amount": invoice_paid_amount,
        "invoice_status": invoice_status,
        "invoice_paid_at": invoice_paid_at,
        "actual_revenue_recognized": actual,
        "actual_paid_at": actual_paid_at,
        "revenue_gap": gap,
        "days_to_payment": _days_to_payment(expected_fee_at, actual_paid_at),
        "clearing_complete_at": clearing_complete_at,
        "ready_for_review_at": transitions.get("ready_for_review_at"),
        "filed_at": transitions.get("filed_at") or (review.filed_at if review else None),
        "closed_at": transitions.get("closed_at"),
        "review_started_at": review.review_started_at if review else None,
        "expected_ack_count": pa.expected_ack_count,
        "tp_comp_date": compute_tp_comp_date(pa),
        "intake_created_at": intake.added_at if intake else None,
        **snapshot,
        **acks,
    }


def sync_assignments(*, pa_ids: set[int] | None = None, full: bool = False) -> int:
    qs = ProductAssignment.objects.select_related(
        "client",
        "product",
        "tax_year",
        "filing_type",
        "preparer",
        "intake__tax_season",
    )
    if not full and pa_ids is not None:
        if not pa_ids:
            return 0
        qs = qs.filter(id__in=pa_ids)
    elif full:
        pass
    else:
        return 0

    count = 0
    for pa in qs.iterator(chunk_size=200):
        row = _build_assignment_row(pa)
        source_pa_id = row.pop("source_pa_id")
        FactAssignment.objects.using("analytics").update_or_create(
            source_pa_id=source_pa_id,
            defaults=row,
        )
        count += 1
    return count


def sync_invoices(*, full: bool = False) -> tuple[int, Any]:
    wm = _get_watermark(WATERMARK_INVOICES)
    qs = Invoice.objects.annotate(linked_pa_count=Count("assignment_links")).order_by("last_activity_at")
    if not full and wm.last_datetime:
        qs = qs.filter(
            Q(last_activity_at__gt=wm.last_datetime) | Q(updated_at__gt=wm.last_datetime)
        )

    max_activity = wm.last_datetime
    count = 0
    for inv in qs.iterator(chunk_size=200):
        amount = _cents_to_decimal(inv.qbo_amount_cents) or Decimal("0")
        balance = _cents_to_decimal(inv.qbo_balance_cents) or Decimal("0")
        paid = (amount - balance).quantize(Decimal("0.01")) if amount else Decimal("0")
        FactInvoice.objects.using("analytics").update_or_create(
            source_invoice_id=inv.id,
            defaults={
                "source_client_id": inv.client_id,
                "status": inv.status or "",
                "qbo_invoice_number": inv.qbo_invoice_number or "",
                "amount": amount,
                "balance": balance,
                "paid_amount": paid,
                "is_paid": inv.is_paid,
                "txn_date": inv.qbo_txn_date,
                "due_date": inv.qbo_due_date,
                "created_at": inv.created_at,
                "last_activity_at": inv.last_activity_at,
                "linked_pa_count": inv.linked_pa_count or 0,
            },
        )
        activity = inv.last_activity_at or inv.updated_at
        if max_activity is None or (activity and activity > max_activity):
            max_activity = activity
        count += 1

    if count or full:
        if not max_activity:
            max_activity = timezone.now()
        _set_watermark(WATERMARK_INVOICES, last_datetime=max_activity)
    return count, max_activity


def sync_acks(*, full: bool = False) -> tuple[int, int]:
    wm = _get_watermark(WATERMARK_ACKS)
    qs = Acknowledgment.objects.select_related("tax_season", "product_assignment").order_by("id")
    if not full and wm.last_int_id:
        qs = qs.filter(id__gt=wm.last_int_id)

    max_id = wm.last_int_id or 0
    count = 0
    for ack in qs.iterator(chunk_size=500):
        FactAck.objects.using("analytics").update_or_create(
            source_ack_id=ack.id,
            defaults={
                "source_pa_id": ack.product_assignment_id,
                "source_client_id": ack.product_assignment.client_id if ack.product_assignment_id else None,
                "tax_season_year": ack.tax_season.year if ack.tax_season_id else None,
                "form_type": ack.type or "",
                "ack_year": ack.year,
                "ack_date": ack.date,
                "status": ack.status or "",
                "client_name": ack.client_name or "",
                "client_tin": ack.client_tin or "",
                "created_at": ack.created_at,
            },
        )
        max_id = max(max_id, ack.id)
        count += 1

    if count or full:
        _set_watermark(WATERMARK_ACKS, last_int_id=max_id)
    return count, max_id


def run_analytics_etl(*, full: bool = False) -> EtlRun:
    if not analytics_enabled():
        raise RuntimeError(
            "Analytics warehouse is disabled. Set ANALYTICS_ENABLED=true and configure ANALYTICS_DB_*."
        )

    run = EtlRun.objects.using("analytics").create(
        status=EtlRun.Status.RUNNING,
        is_full_refresh=full,
    )

    try:
        with transaction.atomic(using="analytics"):
            dim_rows = sync_dimensions()
            ev_rows, _ = sync_lifecycle_events(full=full)

            if full:
                pa_count = sync_assignments(full=True)
                inv_rows, _ = sync_invoices(full=True)
                ack_rows, _ = sync_acks(full=True)
            else:
                pa_ids = _collect_pa_ids_for_incremental()
                pa_count = sync_assignments(pa_ids=pa_ids, full=False)
                inv_rows, _ = sync_invoices(full=False)
                ack_rows, _ = sync_acks(full=False)

            run.rows_dimensions = dim_rows
            run.rows_lifecycle_events = ev_rows
            run.rows_assignments = pa_count
            run.rows_invoices = inv_rows
            run.rows_acks = ack_rows
            run.status = EtlRun.Status.SUCCESS
            run.finished_at = timezone.now()
            run.save(using="analytics")
    except Exception as exc:
        logger.exception("Analytics ETL failed")
        run.status = EtlRun.Status.FAILED
        run.error_message = str(exc)[:4000]
        run.finished_at = timezone.now()
        run.save(using="analytics")
        raise

    logger.info(
        "Analytics ETL complete (full=%s): dims=%s assignments=%s invoices=%s acks=%s events=%s",
        full,
        run.rows_dimensions,
        run.rows_assignments,
        run.rows_invoices,
        run.rows_acks,
        run.rows_lifecycle_events,
    )
    return run
