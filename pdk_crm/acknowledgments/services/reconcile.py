"""Post-filing ack ingestion, PA matching, and lifecycle transitions (Phase 8)."""

from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction

from acknowledgments.services.form_taxonomy import resolve_product_type
from core.models import (
    Acknowledgment,
    AckStaging,
    Client,
    LifecycleState,
    Product,
    ProductAssignment,
    TaxSeason,
    TaxYear,
)
from core.workflows.lifecycle import (
    cmd_close,
    cmd_set_pending_reject_correction,
    cmd_start_ack_reconciling,
)

ACK_ELIGIBLE_LIFECYCLE_STATES = frozenset({
    LifecycleState.FILED,
    LifecycleState.ACK_RECONCILING,
    LifecycleState.PENDING_REJECT_CORRECTION,
})

UNMATCHED_CLEARING_HINT = (
    "No filed ProductAssignment in Clearing. Update tax services in Clearing, then re-import."
)


def normalize_ack_status(raw: str) -> str:
    s = (raw or "").strip().upper()
    if s in ("A", "ACCEPTED", Acknowledgment.STATUS_ACCEPTED):
        return Acknowledgment.STATUS_ACCEPTED
    if s in ("R", "REJECTED", Acknowledgment.STATUS_REJECTED):
        return Acknowledgment.STATUS_REJECTED
    if s in ("PAPER FILED", "PAPER_FILED"):
        return Acknowledgment.STATUS_PAPER_FILED
    if not s or s == Acknowledgment.STATUS_DEFAULT:
        return Acknowledgment.STATUS_DEFAULT
    return raw.strip()


def is_accepted_status(status: str) -> bool:
    return normalize_ack_status(status) == Acknowledgment.STATUS_ACCEPTED


def is_rejected_status(status: str) -> bool:
    return normalize_ack_status(status) == Acknowledgment.STATUS_REJECTED


def set_expected_ack_count(*, pa_id: int, expected_ack_count: int) -> ProductAssignment:
    try:
        count = int(expected_ack_count)
    except (TypeError, ValueError) as exc:
        raise ValidationError({"expected_ack_count": "Must be an integer."}) from exc
    if count < 1:
        raise ValidationError({"expected_ack_count": "Must be at least 1."})

    pa = ProductAssignment.objects.get(id=pa_id)
    pa.expected_ack_count = count
    pa.save(update_fields=["expected_ack_count"])
    return pa


def _staging_payload(st: AckStaging, *, candidates=None) -> dict:
    payload = {
        "id": st.id,
        "match_state": st.match_state,
        "year": st.year,
        "tin": st.client_tin,
        "name": st.client_name,
        "type": st.type,
        "date": st.date.isoformat() if st.date else None,
        "status": st.status,
        "reason": st.reason,
        "suggested_product_type": st.suggested_product_type,
        "suggested_tax_season_year": st.suggested_tax_season_year,
    }
    if candidates is not None:
        payload["candidates"] = candidates
    return payload


@transaction.atomic
def evaluate_pa_lifecycle_after_ack_change(*, pa_id: int, actor=None) -> ProductAssignment:
    pa = ProductAssignment.objects.select_for_update().get(id=pa_id)
    acks = list(pa.acknowledgments.all())
    state = (pa.lifecycle_state or "").strip()

    if any(is_rejected_status(a.status) for a in acks):
        return cmd_set_pending_reject_correction(pa_id=pa.id, actor=actor)

    if state == LifecycleState.PENDING_REJECT_CORRECTION and any(
        is_accepted_status(a.status) for a in acks
    ):
        pa = cmd_start_ack_reconciling(pa_id=pa.id, actor=actor)
        state = pa.lifecycle_state

    expected = pa.expected_ack_count
    if expected is None or expected < 1:
        return pa

    if len(acks) < expected:
        return pa

    if not all(is_accepted_status(a.status) for a in acks):
        return pa

    if state in {LifecycleState.ACK_RECONCILING, LifecycleState.FILED}:
        return cmd_close(pa_id=pa.id, actor=actor)
    return pa


def _ensure_ack_reconciling_started(*, pa: ProductAssignment, actor=None) -> ProductAssignment:
    if pa.lifecycle_state == LifecycleState.FILED:
        return cmd_start_ack_reconciling(pa_id=pa.id, actor=actor)
    return pa


def _attach_ack_to_pa(
    *,
    pa: ProductAssignment,
    tin: str,
    client_name: str,
    tax_year_value: int,
    form_type: str,
    ack_date,
    ack_status: str,
    tax_season: TaxSeason,
    product: Product,
    actor=None,
) -> tuple[Acknowledgment, bool]:
    normalized_status = normalize_ack_status(ack_status)
    ack_obj, created = Acknowledgment.objects.update_or_create(
        product_assignment=pa,
        type=form_type,
        date=ack_date,
        defaults={
            "client_tin": tin,
            "client_name": client_name,
            "year": tax_year_value,
            "status": normalized_status,
            "tax_season": tax_season,
            "product": product,
        },
    )
    pa = _ensure_ack_reconciling_started(pa=pa, actor=actor)
    evaluate_pa_lifecycle_after_ack_change(pa_id=pa.id, actor=actor)
    return ack_obj, created


def _process_single_record(
    rec: dict,
    *,
    active_season: TaxSeason,
    actor=None,
) -> dict:
    tin = (rec.get("client_tin") or "").strip()
    tax_year_value = rec.get("year")
    form_type = (rec.get("type") or "").strip()
    ack_date = rec.get("date")
    ack_status = (rec.get("status") or "").strip()
    client_name = (rec.get("client_name") or "").strip()

    client = Client.objects.filter(TIN=tin).first()
    if not client:
        st = AckStaging.objects.create(
            year=tax_year_value,
            client_tin=tin,
            client_name=client_name,
            type=form_type,
            date=ack_date,
            status=normalize_ack_status(ack_status),
            match_state=AckStaging.MATCH_CLIENT_NOT_FOUND,
            reason="Client TIN not found.",
            suggested_tax_season_year=active_season.year,
        )
        return {"kind": "client_not_found", "staging": _staging_payload(st)}

    product_type, map_error = resolve_product_type(
        form_type=form_type,
        client=client,
        tax_year_value=tax_year_value,
    )
    if map_error:
        match_state = (
            AckStaging.MATCH_NEEDS_FILING_TYPE
            if "filing type" in map_error.lower()
            else AckStaging.MATCH_UNMATCHED
        )
        st = AckStaging.objects.create(
            year=tax_year_value,
            client_tin=tin,
            client_name=client_name,
            type=form_type,
            date=ack_date,
            status=normalize_ack_status(ack_status),
            match_state=match_state,
            reason=map_error,
            suggested_tax_season_year=active_season.year,
        )
        bucket = "needs_filing_type" if match_state == AckStaging.MATCH_NEEDS_FILING_TYPE else "unmatched"
        return {"kind": bucket, "staging": _staging_payload(st)}

    tax_year = TaxYear.objects.filter(client=client, year=tax_year_value).first()
    if not tax_year:
        st = AckStaging.objects.create(
            year=tax_year_value,
            client_tin=tin,
            client_name=client_name,
            type=form_type,
            date=ack_date,
            status=normalize_ack_status(ack_status),
            match_state=AckStaging.MATCH_UNMATCHED,
            reason=UNMATCHED_CLEARING_HINT,
            suggested_tax_season_year=active_season.year,
            suggested_product_type=product_type,
        )
        return {"kind": "unmatched", "staging": _staging_payload(st)}

    product = Product.objects.filter(tax_year=tax_year, product_type=product_type).first()
    if not product:
        st = AckStaging.objects.create(
            year=tax_year_value,
            client_tin=tin,
            client_name=client_name,
            type=form_type,
            date=ack_date,
            status=normalize_ack_status(ack_status),
            match_state=AckStaging.MATCH_UNMATCHED,
            reason=UNMATCHED_CLEARING_HINT,
            suggested_tax_season_year=active_season.year,
            suggested_product_type=product_type,
        )
        return {"kind": "unmatched", "staging": _staging_payload(st)}

    candidates = ProductAssignment.objects.filter(
        client=client,
        tax_year=tax_year,
        product=product,
        is_active=True,
        lifecycle_state__in=ACK_ELIGIBLE_LIFECYCLE_STATES,
    ).select_related("client", "tax_year", "product")

    count = candidates.count()
    if count == 1:
        pa = candidates.first()
        _ack, created = _attach_ack_to_pa(
            pa=pa,
            tin=tin,
            client_name=client_name,
            tax_year_value=tax_year_value,
            form_type=form_type,
            ack_date=ack_date,
            ack_status=ack_status,
            tax_season=active_season,
            product=product,
            actor=actor,
        )
        return {"kind": "matched", "created": created}

    if count == 0:
        st = AckStaging.objects.create(
            year=tax_year_value,
            client_tin=tin,
            client_name=client_name,
            type=form_type,
            date=ack_date,
            status=normalize_ack_status(ack_status),
            match_state=AckStaging.MATCH_UNMATCHED,
            reason=UNMATCHED_CLEARING_HINT,
            suggested_tax_season_year=active_season.year,
            suggested_product_type=product_type,
        )
        return {"kind": "unmatched", "staging": _staging_payload(st)}

    st = AckStaging.objects.create(
        year=tax_year_value,
        client_tin=tin,
        client_name=client_name,
        type=form_type,
        date=ack_date,
        status=normalize_ack_status(ack_status),
        match_state=AckStaging.MATCH_AMBIGUOUS,
        reason=f"Multiple matching filed ProductAssignments found ({count}).",
        suggested_tax_season_year=active_season.year,
        suggested_product_type=product_type,
    )
    return {
        "kind": "ambiguous",
        "staging": {
            **_staging_payload(st),
            "candidates": [pa.id for pa in candidates],
        },
    }


def ingest_ack_records(
    records: list[dict],
    *,
    active_season: TaxSeason,
    actor=None,
) -> dict:
    created_count = 0
    updated_count = 0
    staged_unmatched = []
    staged_ambiguous = []
    staged_needs_filing_type = []
    staged_client_not_found = []

    for rec in records:
        outcome = _process_single_record(rec, active_season=active_season, actor=actor)
        kind = outcome.get("kind")
        if kind == "matched":
            if outcome.get("created"):
                created_count += 1
            else:
                updated_count += 1
        elif kind == "unmatched":
            staged_unmatched.append(outcome["staging"])
        elif kind == "ambiguous":
            staged_ambiguous.append(outcome["staging"])
        elif kind == "needs_filing_type":
            staged_needs_filing_type.append(outcome["staging"])
        elif kind == "client_not_found":
            staged_client_not_found.append(outcome["staging"])

    return {
        "created": created_count,
        "updated": updated_count,
        "unmatched": staged_unmatched,
        "ambiguous": staged_ambiguous,
        "needs_filing_type": staged_needs_filing_type,
        "client_not_found": staged_client_not_found,
    }


def ack_auto_create_enabled() -> bool:
    return getattr(settings, "ACK_ALLOW_AUTO_CREATE_PA", False)
