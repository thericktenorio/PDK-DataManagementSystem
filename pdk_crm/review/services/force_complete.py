"""Force-complete review for stuck reject acks (W5)."""

from __future__ import annotations

from core.workflows.lifecycle import cmd_force_complete_review

from review.models import ReviewEntry
from review.services.queue import ensure_review_entry


def force_complete_review_for_pa(
    *,
    pa_id: int,
    actor,
    note: str,
) -> tuple:
    pa = cmd_force_complete_review(pa_id=pa_id, actor=actor, note=note)
    entry = ensure_review_entry(pa)
    if note:
        entry.notes = note
        entry.save(update_fields=["notes", "updated_at"])
    return pa, entry
