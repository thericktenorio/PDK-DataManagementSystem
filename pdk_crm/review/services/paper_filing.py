"""Record manual paper filings and synthetic compensating acks (W5)."""

from __future__ import annotations

import datetime

from django.core.exceptions import ValidationError
from django.db import transaction

from acknowledgments.services.reconcile import evaluate_pa_lifecycle_after_ack_change
from core.models import (
    Acknowledgment,
    LifecycleState,
    PaperFilingDetail,
    Product,
    ProductAssignment,
)
from core.utils import seed_products_for_tax_year

PAPER_FILE_ELIGIBLE_STATES = frozenset({
    LifecycleState.READY_FOR_REVIEW,
    LifecycleState.FILED,
    LifecycleState.ACK_RECONCILING,
    LifecycleState.PENDING_REJECT_CORRECTION,
})


def _parse_sent_date(raw) -> datetime.date:
    if isinstance(raw, datetime.date):
        return raw
    if isinstance(raw, datetime.datetime):
        return raw.date()
    text = str(raw or "").strip()
    if not text:
        raise ValidationError({"sent_date": "Mail date is required."})
    try:
        return datetime.date.fromisoformat(text)
    except ValueError as exc:
        raise ValidationError({"sent_date": "Use YYYY-MM-DD."}) from exc


def _get_paper_filing_product(pa: ProductAssignment) -> Product:
    seed_products_for_tax_year(pa.tax_year)
    return Product.objects.get(
        tax_year=pa.tax_year,
        product_type=Product.PRODUCT_TYPE_PAPER_FILING,
    )


def record_paper_filing(
    *,
    pa_id: int,
    filings: list[dict],
    actor=None,
) -> ProductAssignment:
    """
    Record one or more paper-filed jurisdictions; creates synthetic ack rows and
    switches the PA product to Paper Filing.
    """
    if not filings:
        raise ValidationError({"filings": "At least one filing entry is required."})

    with transaction.atomic():
        pa = ProductAssignment.objects.select_for_update().get(id=pa_id)
        state = (pa.lifecycle_state or "").strip()
        if state == LifecycleState.CLOSED:
            raise ValidationError({"lifecycle_state": "PA is already filed (closed)."})
        if state not in PAPER_FILE_ELIGIBLE_STATES:
            raise ValidationError(
                {"lifecycle_state": "PA is not eligible for paper filing."}
            )

        tax_season = pa.intake.tax_season
        paper_product = _get_paper_filing_product(pa)
        client = pa.client

        created_count = 0
        for idx, entry in enumerate(filings):
            jurisdiction = (entry.get("jurisdiction") or "").strip().lower()
            if jurisdiction not in {
                PaperFilingDetail.JURISDICTION_FEDERAL,
                PaperFilingDetail.JURISDICTION_STATE,
            }:
                raise ValidationError(
                    {f"filings[{idx}].jurisdiction": "Must be federal or state."}
                )

            form_type = (entry.get("form_type") or "").strip()
            if not form_type:
                raise ValidationError(
                    {f"filings[{idx}].form_type": "Form type is required."}
                )

            mailed_by = (entry.get("mailed_by") or "").strip().lower()
            if mailed_by not in {
                PaperFilingDetail.MAILED_BY_FIRM,
                PaperFilingDetail.MAILED_BY_CLIENT,
            }:
                raise ValidationError(
                    {f"filings[{idx}].mailed_by": "Must be firm or client."}
                )

            sent_date = _parse_sent_date(entry.get("sent_date"))
            tracking = str(entry.get("tracking") or "").strip()
            notes = str(entry.get("notes") or "").strip()

            PaperFilingDetail.objects.create(
                product_assignment=pa,
                jurisdiction=jurisdiction,
                form_type=form_type,
                mailed_by=mailed_by,
                sent_date=sent_date,
                tracking=tracking,
                notes=notes,
                created_by=actor,
            )

            Acknowledgment.objects.create(
                product_assignment=pa,
                product=paper_product,
                tax_season=tax_season,
                type=form_type,
                status=Acknowledgment.STATUS_PAPER_FILED,
                date=sent_date,
                year=pa.tax_year.year if pa.tax_year_id else None,
                client_tin=client.TIN or "",
                client_name=client.name or "",
                description=notes or f"Paper filed by {mailed_by}",
            )
            created_count += 1

        if not pa.expected_ack_count or pa.expected_ack_count < created_count:
            pa.expected_ack_count = created_count
            pa.save(update_fields=["expected_ack_count"])

        pa.product = paper_product
        pa.save(update_fields=["product"])

        if state == LifecycleState.READY_FOR_REVIEW:
            from core.workflows.lifecycle import cmd_mark_filed

            pa = cmd_mark_filed(
                pa_id=pa.id,
                actor=actor,
                expected_ack_count=pa.expected_ack_count,
            )

        return evaluate_pa_lifecycle_after_ack_change(pa_id=pa.id, actor=actor)
