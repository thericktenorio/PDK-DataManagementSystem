from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_POST, require_http_methods
from django.core.exceptions import ValidationError

from core.models import ProductAssignment
from core.utils import get_active_tax_season

from review.permissions import review_access_required, user_can_access_review
from review.selectors import build_review_row, review_queue_queryset
from review.services.queue import mark_filed_for_pa, save_review_notes, start_review_for_pa

import json


def _forbidden_json():
    return JsonResponse(
        {"status": "error", "message": "You do not have access to the review module."},
        status=403,
    )


@review_access_required
@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def review(request):
    tax_season = get_active_tax_season()
    pas = list(review_queue_queryset(tax_season=tax_season))
    rows = [build_review_row(pa) for pa in pas]
    ready_rows = [r for r in rows if r["can_start"]]
    in_review_rows = [r for r in rows if r["can_mark_filed"]]

    return render(
        request,
        "review/review.html",
        {
            "page_title": "Review",
            "tax_season": tax_season,
            "ready_rows": ready_rows,
            "in_review_rows": in_review_rows,
            "queue_count": len(rows),
        },
    )


@require_POST
@review_access_required
def start_review(request, pa_id):
    get_object_or_404(ProductAssignment, id=pa_id)
    try:
        pa, _entry = start_review_for_pa(pa_id=pa_id, actor=request.user)
        row = build_review_row(pa)
        row.pop("pa", None)
        return JsonResponse({"status": "success", "message": "Review started.", **row})
    except ValidationError as ve:
        return JsonResponse(
            {"status": "error", "code": "VALIDATION", "message": ve.message_dict},
            status=400,
        )


@require_POST
@review_access_required
def mark_filed(request, pa_id):
    get_object_or_404(ProductAssignment, id=pa_id)
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse(
            {"status": "error", "message": "Invalid JSON body."}, status=400
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
        pa, _entry = mark_filed_for_pa(
            pa_id=pa_id,
            actor=request.user,
            notes=notes,
            expected_ack_count=expected_ack_count,
        )
        return JsonResponse(
            {
                "status": "success",
                "message": "Marked filed in Drake.",
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
            {"status": "error", "message": "Invalid JSON body."}, status=400
        )

    notes = str(data.get("notes", ""))
    save_review_notes(pa_id=pa.id, notes=notes)
    return JsonResponse({"status": "success", "message": "Notes saved.", "notes": notes})


def review_queue_count_api(request):
    if not user_can_access_review(request.user):
        return _forbidden_json()
    from review.selectors import review_queue_count

    return JsonResponse({"count": review_queue_count()})
