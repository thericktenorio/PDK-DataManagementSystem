"""
Authoritative ProductAssignment lifecycle (replaces CompletionState for new workflow).

Append-only audit: LifecycleTransition.
Idempotent side effects: ProductAssignmentEvent (unique per PA + event_type).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import logging

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from core.models import (
    LifecycleState,
    LifecycleTransition,
    ProductAssignment,
    ProductAssignmentEvent,
)

logger = logging.getLogger(__name__)


ALLOWED_TRANSITIONS: dict[str | None, set[str]] = {
    None: {LifecycleState.IN_CLEARING},
    "": {LifecycleState.IN_CLEARING},
    LifecycleState.IN_CLEARING: {LifecycleState.CLEARING_COMPLETE},
    LifecycleState.CLEARING_COMPLETE: {
        LifecycleState.AWAITING_PAYMENT,
        LifecycleState.READY_FOR_REVIEW,
        LifecycleState.IN_CLEARING,
    },
    LifecycleState.AWAITING_PAYMENT: {
        LifecycleState.READY_FOR_REVIEW,
        LifecycleState.IN_CLEARING,
    },
    LifecycleState.READY_FOR_REVIEW: {
        LifecycleState.IN_REVIEW,
        LifecycleState.FILED,
    },
    LifecycleState.IN_REVIEW: {LifecycleState.FILED},
    LifecycleState.FILED: {
        LifecycleState.ACK_RECONCILING,
        LifecycleState.CLOSED,
    },
    LifecycleState.ACK_RECONCILING: {
        LifecycleState.CLOSED,
        LifecycleState.PENDING_REJECT_CORRECTION,
    },
    LifecycleState.PENDING_REJECT_CORRECTION: {
        LifecycleState.ACK_RECONCILING,
        LifecycleState.CLOSED,
    },
    LifecycleState.CLOSED: set(),
}


FROZEN_FIELDS_AFTER_CLEARING = {
    "filing_type",
    "tax_year",
    "product",
    "fee",
    "discount",
    "payment_method",
    "preparer",
    "closing_message_text",
}

NO_FEE_PAYMENT_METHODS = frozenset({
    ProductAssignment.PAYMENT_METHOD_NO_FEE_PRO_BONO,
    ProductAssignment.PAYMENT_METHOD_NO_FEE_DEPENDENT,
})


WORKFLOW_OWNED_FIELDS = {
    "lifecycle_state",
    "completion_state",
    "parser_status",
    "expected_ack_count",
    "force_completed_at",
    "completed_at",
    "completed_by",
    "is_complete",
    "parse_job_uuid",
    "parse_result_json",
    "parsed_at",
    "parser_output_refs",
}


@dataclass(frozen=True)
class FreezeDecision:
    allowed: bool
    reason: str = ""


def _normalize_state(state: str | None) -> str | None:
    if state is None or state == "":
        return None
    return state


def is_qbo_payment_method(pa: ProductAssignment) -> bool:
    return pa.payment_method == ProductAssignment.PAYMENT_METHOD_QBO


def is_no_fee_payment_method(pa: ProductAssignment) -> bool:
    return (pa.payment_method or "").strip() in NO_FEE_PAYMENT_METHODS


def is_pa_locked_for_editing(pa: ProductAssignment) -> bool:
    """True when lifecycle has left IN_CLEARING (row edits blocked in clearing UI)."""
    state = _normalize_state(pa.lifecycle_state)
    if not state or state == LifecycleState.IN_CLEARING:
        return False
    return True


def validate_pa_ready_for_clearing(pa: ProductAssignment) -> None:
    """
    Required fields before cmd_complete_clearing (Phase 3.7).
    Raises ValidationError with field-keyed messages when incomplete.
    """
    errors: dict[str, str] = {}

    if not pa.filing_type_id:
        errors["filing_type"] = "Filing type is required."
    if not pa.tax_year_id:
        errors["tax_year"] = "Tax year is required."
    if not pa.product_id:
        errors["product"] = "Product is required."

    pm = (pa.payment_method or "").strip()
    if not pm or pm == ProductAssignment.PAYMENT_METHOD_DEFAULT:
        errors["payment_method"] = "Payment method is required."

    if not pa.preparer_id:
        errors["preparer"] = "Preparer is required."

    if not (pa.closing_message_text or "").strip():
        errors["closing_message_text"] = "Client message is required before completing clearing."

    if pm not in NO_FEE_PAYMENT_METHODS:
        if pa.fee is None or pa.fee <= 0:
            errors["fee"] = (
                "Fee must be greater than zero, or select a no-fee payment method. "
                "Verify product catalog default_price is not unintentionally zero."
            )

    if errors:
        raise ValidationError(errors)


def target_state_after_clearing_complete(pa: ProductAssignment) -> str:
    """
    Immediate post-clearing target (Phase 6).
    QBO / non-QBO stay CLEARING_COMPLETE until invoice sent or payment confirmed.
    No-fee advances directly to review.
    """
    if is_no_fee_payment_method(pa):
        return LifecycleState.READY_FOR_REVIEW
    return LifecycleState.CLEARING_COMPLETE


def can_autosave_pa_field(pa: ProductAssignment, field: str) -> FreezeDecision:
    if field in WORKFLOW_OWNED_FIELDS:
        return FreezeDecision(False, f"Field '{field}' is controlled by lifecycle workflow.")

    state = _normalize_state(pa.lifecycle_state)
    if state and state != LifecycleState.IN_CLEARING and field in FROZEN_FIELDS_AFTER_CLEARING:
        return FreezeDecision(False, f"{field} is frozen after clearing is complete.")

    # Legacy completion wizard freeze (deprecated; kept until UI removed)
    from core.models import CompletionState

    if pa.completion_state and pa.completion_state != CompletionState.OPEN:
        if field in FROZEN_FIELDS_AFTER_CLEARING:
            return FreezeDecision(
                False,
                f"{field} is frozen while legacy completion_state={pa.completion_state}.",
            )

    return FreezeDecision(True, "")


def assert_can_transition(pa: ProductAssignment, to_state: str) -> None:
    from_state = _normalize_state(pa.lifecycle_state)
    if from_state == to_state:
        return

    allowed = ALLOWED_TRANSITIONS.get(from_state, set())
    if to_state not in allowed:
        raise ValidationError(
            {"lifecycle_state": f"Illegal transition: {from_state!r} -> {to_state}"}
        )


def _lock_pa(pa_id: int) -> ProductAssignment:
    try:
        return ProductAssignment.objects.select_for_update().get(id=pa_id)
    except ProductAssignment.DoesNotExist:
        raise ValidationError({"pa_id": "ProductAssignment not found."})


def record_lifecycle_transition(
    *,
    pa: ProductAssignment,
    from_state: str | None,
    to_state: str,
    actor=None,
    note: str = "",
    payload: dict | None = None,
) -> LifecycleTransition:
    return LifecycleTransition.objects.create(
        product_assignment=pa,
        from_state=from_state or "",
        to_state=to_state,
        actor=actor,
        note=note,
        payload=payload,
    )


def transition_pa(
    pa: ProductAssignment,
    *,
    to_state: str,
    actor=None,
    note: str = "",
    payload: dict | None = None,
) -> ProductAssignment:
    assert_can_transition(pa, to_state)
    from_state = _normalize_state(pa.lifecycle_state)

    if from_state == to_state:
        return pa

    record_lifecycle_transition(
        pa=pa,
        from_state=from_state,
        to_state=to_state,
        actor=actor,
        note=note,
        payload=payload,
    )

    pa.lifecycle_state = to_state
    pa.full_clean()
    pa.save(update_fields=["lifecycle_state"])
    return pa


def emit_idempotent_event(
    *,
    pa: ProductAssignment,
    event_type: str,
    created_by=None,
    payload: dict | None = None,
) -> bool:
    """
    Returns True if a new event was created, False if it already existed (idempotent).
    """
    try:
        ProductAssignmentEvent.objects.create(
            product_assignment=pa,
            event_type=event_type,
            created_by=created_by,
            payload=payload,
        )
        return True
    except IntegrityError:
        return False


# ---------- Commands ----------


def cmd_enter_clearing(*, pa_id: int, actor=None) -> ProductAssignment:
    with transaction.atomic():
        pa = _lock_pa(pa_id)
        state = _normalize_state(pa.lifecycle_state)
        if state is None:
            return transition_pa(
                pa,
                to_state=LifecycleState.IN_CLEARING,
                actor=actor,
                note="Entered daily clearing",
            )
        if state == LifecycleState.IN_CLEARING:
            return pa
        # Already past clearing — idempotent noop when re-adding client to clearing
        return pa


def cmd_complete_clearing(*, pa_id: int, actor=None) -> ProductAssignment:
    with transaction.atomic():
        pa = _lock_pa(pa_id)
        state = _normalize_state(pa.lifecycle_state)
        if state == LifecycleState.CLEARING_COMPLETE:
            return pa
        if state != LifecycleState.IN_CLEARING:
            raise ValidationError(
                {"lifecycle_state": "PA must be IN_CLEARING to complete clearing."}
            )
        validate_pa_ready_for_clearing(pa)
        pa = transition_pa(
            pa,
            to_state=LifecycleState.CLEARING_COMPLETE,
            actor=actor,
            note="Clearing completed",
        )
        emit_idempotent_event(
            pa=pa,
            event_type=ProductAssignmentEvent.EventType.CLEARING_COMPLETED,
            created_by=actor,
            payload={"payment_method": pa.payment_method},
        )
        return pa


def cmd_apply_post_clearing_payment_gate(*, pa_id: int, actor=None) -> ProductAssignment:
    """
    Legacy helper: only no-fee PAs auto-advance from CLEARING_COMPLETE.
    QBO waits for invoice send; other non-QBO wait for cmd_confirm_payment_received.
    """
    with transaction.atomic():
        pa = _lock_pa(pa_id)
        state = _normalize_state(pa.lifecycle_state)
        if state == LifecycleState.READY_FOR_REVIEW:
            return pa
        if state != LifecycleState.CLEARING_COMPLETE:
            raise ValidationError(
                {"lifecycle_state": "PA must be CLEARING_COMPLETE to apply payment gate."}
            )
        if not is_no_fee_payment_method(pa):
            return pa
        return cmd_mark_ready_for_review(pa_id=pa_id, actor=actor)


def cmd_confirm_payment_received(*, pa_id: int, actor=None) -> ProductAssignment:
    """Non-QBO (non-no-fee): staff confirms payment while PA is CLEARING_COMPLETE."""
    with transaction.atomic():
        pa = _lock_pa(pa_id)
        state = _normalize_state(pa.lifecycle_state)
        if state == LifecycleState.READY_FOR_REVIEW:
            return pa
        if state != LifecycleState.CLEARING_COMPLETE:
            raise ValidationError(
                {"lifecycle_state": "PA must be CLEARING_COMPLETE to confirm payment."}
            )
        if is_qbo_payment_method(pa):
            raise ValidationError(
                {"payment_method": "QBO clients advance when the linked invoice is paid."}
            )
        if is_no_fee_payment_method(pa):
            raise ValidationError(
                {"payment_method": "No-fee assignments advance automatically at clearing complete."}
            )
        return cmd_mark_ready_for_review(pa_id=pa_id, actor=actor)


def cmd_mark_awaiting_payment(*, pa_id: int, actor=None) -> ProductAssignment:
    with transaction.atomic():
        pa = _lock_pa(pa_id)
        if _normalize_state(pa.lifecycle_state) == LifecycleState.AWAITING_PAYMENT:
            return pa
        return transition_pa(
            pa,
            to_state=LifecycleState.AWAITING_PAYMENT,
            actor=actor,
            note="Awaiting QBO payment",
        )


def cmd_mark_ready_for_review(*, pa_id: int, actor=None) -> ProductAssignment:
    with transaction.atomic():
        pa = _lock_pa(pa_id)
        state = _normalize_state(pa.lifecycle_state)
        if state == LifecycleState.READY_FOR_REVIEW:
            return pa
        if state not in {
            LifecycleState.CLEARING_COMPLETE,
            LifecycleState.AWAITING_PAYMENT,
        }:
            raise ValidationError(
                {"lifecycle_state": "PA must be CLEARING_COMPLETE or AWAITING_PAYMENT."}
            )
        pa = transition_pa(
            pa,
            to_state=LifecycleState.READY_FOR_REVIEW,
            actor=actor,
            note="Ready for review",
        )
        emit_idempotent_event(
            pa=pa,
            event_type=ProductAssignmentEvent.EventType.READY_FOR_REVIEW,
            created_by=actor,
        )
        return pa


def cmd_start_review(*, pa_id: int, actor=None) -> ProductAssignment:
    with transaction.atomic():
        pa = _lock_pa(pa_id)
        if _normalize_state(pa.lifecycle_state) == LifecycleState.IN_REVIEW:
            return pa
        return transition_pa(
            pa,
            to_state=LifecycleState.IN_REVIEW,
            actor=actor,
            note="Review started",
        )


def cmd_mark_filed(
    *,
    pa_id: int,
    actor=None,
    expected_ack_count: int | None = None,
) -> ProductAssignment:
    with transaction.atomic():
        pa = _lock_pa(pa_id)
        if expected_ack_count is not None:
            try:
                count = int(expected_ack_count)
            except (TypeError, ValueError) as exc:
                raise ValidationError(
                    {"expected_ack_count": "Must be an integer."}
                ) from exc
            if count < 1:
                raise ValidationError(
                    {"expected_ack_count": "Must be at least 1."}
                )
            pa.expected_ack_count = count
            pa.save(update_fields=["expected_ack_count"])
        elif pa.expected_ack_count is None:
            pa.expected_ack_count = 1
            pa.save(update_fields=["expected_ack_count"])

        if _normalize_state(pa.lifecycle_state) == LifecycleState.FILED:
            return pa
        pa = transition_pa(
            pa,
            to_state=LifecycleState.FILED,
            actor=actor,
            note="Marked filed in Drake",
        )
        emit_idempotent_event(
            pa=pa,
            event_type=ProductAssignmentEvent.EventType.FILED,
            created_by=actor,
        )
        return pa


def cmd_start_ack_reconciling(*, pa_id: int, actor=None) -> ProductAssignment:
    with transaction.atomic():
        pa = _lock_pa(pa_id)
        if _normalize_state(pa.lifecycle_state) == LifecycleState.ACK_RECONCILING:
            return pa
        return transition_pa(
            pa,
            to_state=LifecycleState.ACK_RECONCILING,
            actor=actor,
            note="Ack reconciliation started",
        )


def cmd_close(*, pa_id: int, actor=None) -> ProductAssignment:
    with transaction.atomic():
        pa = _lock_pa(pa_id)
        if _normalize_state(pa.lifecycle_state) == LifecycleState.CLOSED:
            return pa
        pa = transition_pa(
            pa,
            to_state=LifecycleState.CLOSED,
            actor=actor,
            note="All acks accepted",
        )
        emit_idempotent_event(
            pa=pa,
            event_type=ProductAssignmentEvent.EventType.CLOSED,
            created_by=actor,
        )
        return pa


FORCE_COMPLETE_ELIGIBLE_STATES = frozenset({
    LifecycleState.PENDING_REJECT_CORRECTION,
    LifecycleState.FILED,
    LifecycleState.ACK_RECONCILING,
})


def cmd_force_complete_review(
    *,
    pa_id: int,
    actor=None,
    note: str = "",
) -> ProductAssignment:
    """Close a PA despite stuck reject acks; force date counts as A for TP Comp Dt."""
    note = (note or "").strip()
    if not note:
        raise ValidationError({"note": "A note is required for force completion."})

    with transaction.atomic():
        pa = _lock_pa(pa_id)
        state = _normalize_state(pa.lifecycle_state)
        if state == LifecycleState.CLOSED:
            return pa
        if state not in FORCE_COMPLETE_ELIGIBLE_STATES:
            raise ValidationError(
                {
                    "lifecycle_state": (
                        "PA must be pending reject correction or pending acknowledgments "
                        "to force complete."
                    )
                }
            )

        pa.force_completed_at = timezone.now()
        pa.save(update_fields=["force_completed_at"])

        pa = transition_pa(
            pa,
            to_state=LifecycleState.CLOSED,
            actor=actor,
            note=note,
            payload={"force_completed": True},
        )
        emit_idempotent_event(
            pa=pa,
            event_type=ProductAssignmentEvent.EventType.CLOSED,
            created_by=actor,
            payload={"force_completed": True},
        )
        return pa


def cmd_set_pending_reject_correction(
    *, pa_id: int, actor=None, reason: str = ""
) -> ProductAssignment:
    with transaction.atomic():
        pa = _lock_pa(pa_id)
        if _normalize_state(pa.lifecycle_state) == LifecycleState.PENDING_REJECT_CORRECTION:
            return pa
        return transition_pa(
            pa,
            to_state=LifecycleState.PENDING_REJECT_CORRECTION,
            actor=actor,
            note=reason or "Reject ack received",
        )


def cmd_set_pending_reject(*, pa_id: int, actor=None, reason: str = "") -> ProductAssignment:
    """Deprecated alias for cmd_set_pending_reject_correction."""
    return cmd_set_pending_reject_correction(pa_id=pa_id, actor=actor, reason=reason)


def cmd_reopen_clearing(
    *,
    pa_id: int,
    actor=None,
    confirmed_fee,
    acknowledge_invoice_sent: bool = False,
) -> ProductAssignment:
    """Reopen a completed clearing row; fee must be explicitly confirmed (Phase 3/6)."""
    with transaction.atomic():
        pa = _lock_pa(pa_id)
        state = _normalize_state(pa.lifecycle_state)
        if state == LifecycleState.IN_CLEARING:
            return pa
        if state not in {
            LifecycleState.CLEARING_COMPLETE,
            LifecycleState.AWAITING_PAYMENT,
        }:
            raise ValidationError(
                {
                    "lifecycle_state": (
                        "PA must be CLEARING_COMPLETE or AWAITING_PAYMENT to reopen clearing."
                    )
                }
            )

        if state == LifecycleState.AWAITING_PAYMENT and not acknowledge_invoice_sent:
            raise ValidationError(
                {
                    "acknowledge_invoice_sent": (
                        "Invoice was already sent to QBO. Confirm to unlock anyway."
                    )
                }
            )

        try:
            fee_value = Decimal(str(confirmed_fee))
        except (InvalidOperation, TypeError):
            raise ValidationError({"confirmed_fee": "Invalid fee value."}) from None

        if fee_value < 0:
            raise ValidationError({"confirmed_fee": "Fee cannot be negative."})

        pm = (pa.payment_method or "").strip()
        if pm not in NO_FEE_PAYMENT_METHODS and fee_value <= 0:
            raise ValidationError(
                {"confirmed_fee": "Fee must be greater than zero for this payment method."}
            )

        pa.fee = fee_value
        pa.full_clean()
        pa.save(update_fields=["fee"])

        return transition_pa(
            pa,
            to_state=LifecycleState.IN_CLEARING,
            actor=actor,
            note="Clearing reopened",
            payload={
                "confirmed_fee": str(fee_value),
                "payment_method": pa.payment_method,
            },
        )


def cmd_void_pa_for_parse_replace(
    *,
    pa_id: int,
    actor=None,
    superseded_by_pa_id: int | None = None,
) -> ProductAssignment:
    """Void a PA when global upload replaces its parse data (audit-friendly supersede)."""
    with transaction.atomic():
        pa = _lock_pa(pa_id)
        if is_pa_locked_for_editing(pa):
            raise ValidationError(
                {
                    "__all__": (
                        "This entry has already completed clearing. "
                        "Create a new entry with the appropriate fee instead."
                    )
                }
            )

        pa.is_active = False
        pa.voided_at = timezone.now()
        pa.voided_by = actor
        pa.void_reason = ProductAssignment.VoidReason.PDF_REPLACED
        update_fields = ["is_active", "voided_at", "voided_by", "void_reason"]
        if superseded_by_pa_id is not None:
            pa.superseded_by_id = superseded_by_pa_id
            update_fields.append("superseded_by")
        pa.save(update_fields=update_fields)

        emit_idempotent_event(
            pa=pa,
            event_type=ProductAssignmentEvent.EventType.PARSE_SUPERSEDED,
            created_by=actor,
            payload={
                "parse_job_uuid": str(pa.parse_job_uuid) if pa.parse_job_uuid else None,
                "superseded_by_pa_id": superseded_by_pa_id,
            },
        )
        return pa


def enter_clearing_for_client_assignments(
    *,
    client_id: int,
    intake_id: int | None = None,
    actor=None,
) -> list[ProductAssignment]:
    """Call when a client is added to daily clearing (all active PAs for intake)."""
    qs = ProductAssignment.objects.filter(client_id=client_id, is_active=True)
    if intake_id is not None:
        qs = qs.filter(intake_id=intake_id)
    updated: list[ProductAssignment] = []
    for pa in qs:
        updated.append(cmd_enter_clearing(pa_id=pa.id, actor=actor))
    return updated
