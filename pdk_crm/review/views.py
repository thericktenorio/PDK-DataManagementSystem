from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_POST, require_http_methods
from django.core.exceptions import ValidationError

from core.models import ProductAssignment
from core.utils import get_active_tax_season

from review.permissions import review_access_required, user_can_access_review
from review.selectors import build_review_row, review_queue_count, review_table_queryset
from review.services.force_complete import force_complete_review_for_pa
from review.services.paper_filing import record_paper_filing
from review.services.queue import (
    complete_reject_correction_for_pa,
    complete_review_for_pa,
    save_review_notes,
)

import json


def _forbidden_json():
    return JsonResponse(
        {"status": "error", "message": "You do not have access to the review module."},
        status=403,
    )


def _rows_for_table(table: str, *, tax_season):
    pas = list(review_table_queryset(table=table, tax_season=tax_season))
    return [build_review_row(pa) for pa in pas]


@review_access_required
@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def review(request):
    tax_season = get_active_tax_season()

    return render(
        request,
        "review/review.html",
        {
            "page_title": "Review",
            "tax_season": tax_season,
            "ready_rows": _rows_for_table("ready", tax_season=tax_season),
            "pending_ack_rows": _rows_for_table("pending_acks", tax_season=tax_season),
            "pending_reject_rows": _rows_for_table("pending_reject", tax_season=tax_season),
            "filed_rows": _rows_for_table("filed", tax_season=tax_season),
            "queue_count": review_queue_count(tax_season=tax_season),
        },
    )


@require_POST
@review_access_required
def complete_review(request, pa_id):
    get_object_or_404(ProductAssignment, id=pa_id)
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse(
            {"status": "error", "message": "Invalid JSON body."},
            status=400,
        )

    notes = data.get("notes")
    if notes is not None:
        notes = str(notes)

    expected_ack_count = data.get("expected_ack_count")
    if expected_ack_count is not None:
        try:
            expected_ack_count = int(expected_ack_count)
        except (TypeError, ValueError):
            return JsonResponse(
                {"status": "error", "message": "expected_ack_count must be an integer."},
                status=400,
            )

    try:
        pa, _entry = complete_review_for_pa(
            pa_id=pa_id,
            actor=request.user,
            notes=notes,
            expected_ack_count=expected_ack_count,
        )
        return JsonResponse(
            {
                "status": "success",
                "message": "Review complete; pending acknowledgments.",
                "pa_id": pa.id,
                "lifecycle_state": pa.lifecycle_state,
                "expected_ack_count": pa.expected_ack_count,
            }
        )
    except ValidationError as ve:
        return JsonResponse(
            {"status": "error", "code": "VALIDATION", "message": ve.message_dict},
            status=400,
        )


@require_POST
@review_access_required
def complete_reject_correction(request, pa_id):
    get_object_or_404(ProductAssignment, id=pa_id)
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse(
            {"status": "error", "message": "Invalid JSON body."},
            status=400,
        )

    notes = data.get("notes")
    if notes is not None:
        notes = str(notes)

    try:
        pa, _entry = complete_reject_correction_for_pa(
            pa_id=pa_id,
            actor=request.user,
            notes=notes,
        )
        return JsonResponse(
            {
                "status": "success",
                "message": "Reject correction complete; pending acknowledgments.",
                "pa_id": pa.id,
                "lifecycle_state": pa.lifecycle_state,
            }
        )
    except ValidationError as ve:
        return JsonResponse(
            {"status": "error", "code": "VALIDATION", "message": ve.message_dict},
            status=400,
        )


@require_http_methods(["GET", "POST"])
@review_access_required
def review_notes(request, pa_id):
    pa = get_object_or_404(ProductAssignment, id=pa_id)

    if request.method == "GET":
        row = build_review_row(pa)
        return JsonResponse({"status": "success", "notes": row["notes"]})

    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse(
            {"status": "error", "message": "Invalid JSON body."},
            status=400,
        )

    notes = str(data.get("notes", ""))
    save_review_notes(pa_id=pa.id, notes=notes)
    return JsonResponse({"status": "success", "message": "Notes saved.", "notes": notes})


def review_queue_count_api(request):
    if not user_can_access_review(request.user):
        return _forbidden_json()
    return JsonResponse({"count": review_queue_count()})


@require_POST
@review_access_required
def force_complete_review(request, pa_id):
    get_object_or_404(ProductAssignment, id=pa_id)
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse(
            {"status": "error", "message": "Invalid JSON body."},
            status=400,
        )

    note = str(data.get("note") or "").strip()
    if not note:
        return JsonResponse(
            {"status": "error", "message": "A note is required for force completion."},
            status=400,
        )

    try:
        pa, _entry = force_complete_review_for_pa(
            pa_id=pa_id,
            actor=request.user,
            note=note,
        )
        return JsonResponse(
            {
                "status": "success",
                "message": "Force completed; assignment filed.",
                "pa_id": pa.id,
                "lifecycle_state": pa.lifecycle_state,
            }
        )
    except ValidationError as ve:
        return JsonResponse(
            {"status": "error", "code": "VALIDATION", "message": ve.message_dict},
            status=400,
        )


@require_POST
@review_access_required
def paper_filing(request, pa_id):
    get_object_or_404(ProductAssignment, id=pa_id)
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse(
            {"status": "error", "message": "Invalid JSON body."},
            status=400,
        )

    filings = data.get("filings")
    if not isinstance(filings, list) or not filings:
        return JsonResponse(
            {"status": "error", "message": "filings must be a non-empty list."},
            status=400,
        )

    try:
        pa = record_paper_filing(
            pa_id=pa_id,
            filings=filings,
            actor=request.user,
        )
        return JsonResponse(
            {
                "status": "success",
                "message": "Paper filing recorded.",
                "pa_id": pa.id,
                "lifecycle_state": pa.lifecycle_state,
                "product_type": pa.product.product_type if pa.product_id else "",
            }
        )
    except ValidationError as ve:
        return JsonResponse(
            {"status": "error", "code": "VALIDATION", "message": ve.message_dict},
            status=400,
        )
