from django.utils import timezone

from core.workflows.lifecycle import cmd_mark_filed, cmd_start_review

from review.models import ReviewEntry


def ensure_review_entry(pa) -> ReviewEntry:
    entry, _ = ReviewEntry.objects.get_or_create(product_assignment=pa)
    return entry


def start_review_for_pa(*, pa_id: int, actor):
    pa = cmd_start_review(pa_id=pa_id, actor=actor)
    entry = ensure_review_entry(pa)
    now = timezone.now()
    entry.assigned_reviewer = actor
    if entry.review_started_at is None:
        entry.review_started_at = now
    entry.save(update_fields=["assigned_reviewer", "review_started_at", "updated_at"])
    return pa, entry


def mark_filed_for_pa(
    *,
    pa_id: int,
    actor,
    notes: str | None = None,
    expected_ack_count: int | None = None,
):
    pa = cmd_mark_filed(
        pa_id=pa_id,
        actor=actor,
        expected_ack_count=expected_ack_count,
    )
    entry = ensure_review_entry(pa)
    now = timezone.now()
    if notes is not None:
        entry.notes = notes
    entry.filed_at = now
    entry.filed_by = actor
    entry.save(update_fields=["notes", "filed_at", "filed_by", "updated_at"])
    return pa, entry


def save_review_notes(*, pa_id: int, notes: str) -> ReviewEntry:
    from core.models import ProductAssignment

    pa = ProductAssignment.objects.get(id=pa_id)
    entry = ensure_review_entry(pa)
    entry.notes = notes
    entry.save(update_fields=["notes", "updated_at"])
    return entry
