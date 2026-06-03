"""
Deprecated: legacy completion wizard (parser → ack count → COMPLETED).

New workflow: core/workflows/lifecycle.py. UI still calls these endpoints until Phase 3.
"""
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.db import transaction, IntegrityError

from core.models import ProductAssignment, CompletionState, ParserStatus, ProductAssignmentEvent

from dataclasses import dataclass
from typing import Iterable

import logging


ALLOWED_TRANSITIONS = {
    CompletionState.OPEN: {
        CompletionState.PENDING_PARSER,
        CompletionState.PARSER_SKIPPED,
    },
    CompletionState.PENDING_PARSER: {
        CompletionState.PARSER_RUNNING,
        CompletionState.PARSER_SKIPPED,
    },
    CompletionState.PARSER_RUNNING: {
        CompletionState.PARSER_DONE,
    },
    CompletionState.PARSER_DONE: {
        CompletionState.PENDING_ACK_COUNT,
    },
    CompletionState.PARSER_SKIPPED: {
        CompletionState.PENDING_ACK_COUNT,
    },
    CompletionState.PENDING_ACK_COUNT: {
        CompletionState.READY_TO_COMPLETE,
    },
    CompletionState.READY_TO_COMPLETE: {
        CompletionState.COMPLETED,
    },
    CompletionState.COMPLETED: set(),
}


FROZEN_FIELDS_ON_COMPLETION_START = {
    "filing_type",
    "tax_year",
    "product",
    "fee",
    "discount",
    "payment_method",
}


WORKFLOW_OWNED_FIELDS = {
    # never writable by autosave (only via commands)
    "completion_state",
    "parser_status",
    "expected_ack_count",
    "completed_at",
    "completed_by",
    "is_complete",  # consider treating as derived/workflow-owned
}


@dataclass(frozen = True)
class FreezeDecision:
    allowed: bool
    reason: str = ""


def can_autosave_pa_field(pa: ProductAssignment, field: str) -> FreezeDecision:
    from core.workflows.lifecycle import can_autosave_pa_field as lifecycle_can_autosave

    return lifecycle_can_autosave(pa, field)


# helper function to ensure: 
    # 1) idepotency and
    # 2) the allowed state is within the list of permitted completion states
def assert_can_transition(pa: ProductAssignment, to_state: str):
    from_state = pa.completion_state

    if from_state == to_state:
        return # idempotent no-op
    
    allowed = ALLOWED_TRANSITIONS.get(from_state, set())
    if to_state not in allowed:
        raise ValidationError({"completion_state": f"Illegal transition: {from_state} -> {to_state}"})


# transiitons product assignment from one completion state to the next
def transition_pa(pa: ProductAssignment, *, to_state: str, parser_status: str | None = None, completed_by = None):
    # check if transition is allowed
    assert_can_transition(pa, to_state)

    pa.completion_state = to_state

    if parser_status is not None:
        pa.parser_status = parser_status
    
    if to_state == CompletionState.COMPLETED:
        pa.completed_at = pa.completed_at or timezone.now()
        pa.completed_by = pa.completed_by or completed_by
        pa.is_complete = True

    pa.full_clean()
    pa.save()


def _lock_pa(pa_id: int) -> ProductAssignment:
    try:
        return ProductAssignment.objects.select_for_update().get(id = pa_id)
    except ProductAssignment.DoesNotExist:
        raise ValidationError({"pa_id": "ProductAssignment not found."})


def cmd_start_completion(*, pa_id: int) -> ProductAssignment:
    with transaction.atomic():
        pa = _lock_pa(pa_id)

        if pa.completion_state != CompletionState.OPEN:
            return pa   #noop
        
        transition_pa(
            pa,
            to_state = CompletionState.PENDING_PARSER,
            parser_status = ParserStatus.NOT_STARTED,
        )
        return pa
    

def cmd_skip_parser(*, pa_id: int) -> ProductAssignment:
    with transaction.atomic():
        pa = _lock_pa(pa_id)

        # already skipped or beyond -> noop
        if pa.completion_state in {
            CompletionState.PARSER_SKIPPED,
            CompletionState.PENDING_ACK_COUNT,
            CompletionState.READY_TO_COMPLETE,
            CompletionState.COMPLETED,
        }:
            return pa
        
        # only allowed form OPEN / PENDING_PARSER
        if pa.completion_state not in {CompletionState.OPEN, CompletionState.PENDING_PARSER}:
            raise ValidationError({"completion_state": "Cannot skip parser from current state."})
        
        transition_pa(pa, to_state = CompletionState.PARSER_SKIPPED, parser_status = ParserStatus.SKIPPED)
        return pa
    

def cmd_begin_ack_count(*, pa_id: int) -> ProductAssignment:
    with transaction.atomic():
        pa = _lock_pa(pa_id)

        # noop if already there or beyond
        if pa.completion_state in {
            CompletionState.PENDING_ACK_COUNT,
            CompletionState.READY_TO_COMPLETE,
            CompletionState.COMPLETED,
        }:
            return pa
        
        # only allowed from PARSER_SKIPPED or PARSER_DONE (make sure this method and the UI are congruent)
        if pa.completion_state not in {CompletionState.PARSER_SKIPPED, CompletionState.PARSER_DONE}:
            raise ValidationError({"completion_state": "Cannot enter ack-count step from current state."})

        transition_pa(pa, to_state = CompletionState.PENDING_ACK_COUNT)
        return pa
    
    
def cmd_set_expected_ack_count(*, pa_id: int, expected_ack_count: int) -> ProductAssignment:
    try:
        expected_ack_count = int(expected_ack_count)
    except (TypeError, ValueError):
        raise ValidationError({"expected_ack_count": "Must be an integer."})
    
    if expected_ack_count < 0:
        raise ValidationError({"expected_ack_count": "Must be >= 0."})
    
    with transaction.atomic():
        pa = _lock_pa(pa_id)

        # idempotent: ready with same acknowledgment count
        if pa.completion_state == CompletionState.READY_TO_COMPLETE:
            if pa.expected_ack_count == expected_ack_count:
                return pa
            raise ValidationError({"completion_state": "Already READY_TO_COMPLETE; cannot change expected_ack_count."})
        
        if pa.completion_state != CompletionState.PENDING_ACK_COUNT:
            raise ValidationError({"completion_state": "PA not in PENDING_ACK_COUNT."})
        
        pa.expected_ack_count = expected_ack_count
        transition_pa(pa, to_state = CompletionState.READY_TO_COMPLETE)
        
        return pa


# PA_COMPLETED stub
logger = logging.getLogger(__name__)
def emit_pa_completed(pa: ProductAssignment, *, created_by = None):
    """
    DB-backed idempotent event emission
    Safe under double finalize + concurrent finalize
    """
    try:
        ProductAssignmentEvent.objects.create(
            product_assignment = pa,
            event_type = ProductAssignmentEvent.EventType.PA_COMPLETED,
            created_by = created_by,
            payload = {
                "client_id": pa.client_id,
                "tax_year_id": pa.tax_year_id,
                "product_id": pa.product_id,
                "completed_at": (pa.completed_at.isoformat() if pa.completed_at else None),
                "completed_by_id": pa.completed_by_id,
            },
        )
        logger.info(
            "PA_COMPLETED emitted pa_id=%s client_id=%s tax_year_id=%s product_id=%s completed_at=%s completed_by_id=%s",
            pa.id,
            pa.client_id,
            pa.tax_year_id,
            pa.product_id,
            pa.completed_at,
            pa.completed_by_id,
        )
    except IntegrityError:
        # unique constraint hit => event already exists => idempotent success
        logger.info("PA_COMPLETED already emitted pa_id=%s (noop)", pa.id)


def cmd_finalize_completion(*, pa_id: int, completed_by) -> ProductAssignment:
    with transaction.atomic():
        pa = _lock_pa(pa_id)

        if pa.completion_state == CompletionState.COMPLETED:
            return pa   #noop
        
        if pa.completion_state != CompletionState.READY_TO_COMPLETE:
            raise ValidationError({"completion_state": "PA not READY_TO_COMPLETE."})
        
        transition_pa(pa, to_state = CompletionState.COMPLETED, completed_by = completed_by)
        emit_pa_completed(pa, created_by = completed_by)
        return pa


def cmd_cancel_completion(*, pa_id: int) -> ProductAssignment:
    with transaction.atomic():
        pa = _lock_pa(pa_id)

        if pa.completion_state == CompletionState.COMPLETED:
            return pa #noop
        
        pa.completion_state = CompletionState.OPEN
        pa.parser_status = ParserStatus.NOT_STARTED
        pa.expected_ack_count = None
        pa.completed_at = None
        pa.completed_by = None
        pa.closing_message_text = None
        pa.is_complete = False

        pa.full_clean()
        pa.save()

        return pa