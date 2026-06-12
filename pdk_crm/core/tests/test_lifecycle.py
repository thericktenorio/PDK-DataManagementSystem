import uuid
import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.core.exceptions import ValidationError

from core.models import (
    Organization,
    Client,
    TaxSeason,
    TaxYear,
    Product,
    FilingType,
    Intake,
    ProductAssignment,
    LifecycleState,
    LifecycleTransition,
    ProductAssignmentEvent,
)
from core.workflows.lifecycle import (
    cmd_enter_clearing,
    cmd_complete_clearing,
    cmd_reopen_clearing,
    cmd_apply_post_clearing_payment_gate,
    cmd_confirm_payment_received,
    cmd_cancel_assignment,
    validate_pa_ready_for_clearing,
    cmd_mark_ready_for_review,
    cmd_start_review,
    cmd_mark_filed,
    cmd_start_ack_reconciling,
    cmd_close,
    cmd_set_pending_reject_correction,
    target_state_after_clearing_complete,
)

User = get_user_model()


class LifecycleWorkflowTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name=f"Org {uuid.uuid4().hex[:8]}")
        self.preparer = User.objects.create_user(
            email=f"prep-{uuid.uuid4().hex[:8]}@example.com",
            password="testpass123",
            organization=self.org,
            role="tax_preparer",
        )
        self.client_obj = Client.objects.create(TIN="123456789", name="Test Client")
        self.tax_season = TaxSeason.objects.create(
            year=2025,
            start_date=datetime.date(2025, 1, 1),
            end_date=datetime.date(2025, 10, 15),
            is_active=True,
        )
        self.intake = Intake.objects.create(
            client=self.client_obj,
            tax_season=self.tax_season,
            is_active=True,
        )
        self.tax_year = TaxYear.objects.create(client=self.client_obj, year=2024)
        self.product = Product.objects.create(
            tax_year=self.tax_year,
            product_type=Product.PRODUCT_TYPE_DEFAULT,
            is_product_active=False,
            default_price="100.00",
        )
        self.filing_type = FilingType.objects.create(
            filing_type=FilingType.FILING_TYPE_DEFAULT
        )
        self.pa = ProductAssignment.objects.create(
            client=self.client_obj,
            intake=self.intake,
            tax_year=self.tax_year,
            product=self.product,
            filing_type=self.filing_type,
            is_active=True,
        )

    def _make_pa_ready_for_clearing(self, *, payment_method=ProductAssignment.PAYMENT_METHOD_CASH):
        self.pa.refresh_from_db()
        self.pa.payment_method = payment_method
        self.pa.fee = Decimal(str(self.product.default_price))
        self.pa.preparer = self.preparer
        self.pa.closing_message_text = "Your documents are ready."
        self.pa.save(
            update_fields=[
                "payment_method",
                "fee",
                "preparer",
                "closing_message_text",
            ]
        )

    def test_enter_clearing_from_null(self):
        pa = cmd_enter_clearing(pa_id=self.pa.id)
        self.assertEqual(pa.lifecycle_state, LifecycleState.IN_CLEARING)
        self.assertEqual(LifecycleTransition.objects.filter(product_assignment=pa).count(), 1)

    def test_complete_clearing_idempotent_event(self):
        cmd_enter_clearing(pa_id=self.pa.id)
        self._make_pa_ready_for_clearing()
        pa = cmd_complete_clearing(pa_id=self.pa.id)
        self.assertEqual(pa.lifecycle_state, LifecycleState.CLEARING_COMPLETE)
        cnt = ProductAssignmentEvent.objects.filter(
            product_assignment=pa,
            event_type=ProductAssignmentEvent.EventType.CLEARING_COMPLETED,
        ).count()
        self.assertEqual(cnt, 1)
        cmd_complete_clearing(pa_id=self.pa.id)
        self.assertEqual(
            ProductAssignmentEvent.objects.filter(
                product_assignment=pa,
                event_type=ProductAssignmentEvent.EventType.CLEARING_COMPLETED,
            ).count(),
            1,
        )

    def test_payment_gate_qbo_vs_cash(self):
        self._make_pa_ready_for_clearing(payment_method=ProductAssignment.PAYMENT_METHOD_QBO)
        cmd_enter_clearing(pa_id=self.pa.id)
        cmd_complete_clearing(pa_id=self.pa.id)
        self.pa.refresh_from_db()
        self.assertEqual(
            target_state_after_clearing_complete(self.pa),
            LifecycleState.CLEARING_COMPLETE,
        )

        self.pa.payment_method = ProductAssignment.PAYMENT_METHOD_CASH
        self.pa.save(update_fields=["payment_method"])
        self.assertEqual(
            target_state_after_clearing_complete(self.pa),
            LifecycleState.CLEARING_COMPLETE,
        )

        self.pa.payment_method = ProductAssignment.PAYMENT_METHOD_NO_FEE_PRO_BONO
        self.pa.save(update_fields=["payment_method"])
        self.assertEqual(
            target_state_after_clearing_complete(self.pa),
            LifecycleState.READY_FOR_REVIEW,
        )

    def test_full_happy_path_to_closed(self):
        cmd_enter_clearing(pa_id=self.pa.id)
        self._make_pa_ready_for_clearing()
        cmd_complete_clearing(pa_id=self.pa.id)
        cmd_confirm_payment_received(pa_id=self.pa.id)
        cmd_start_review(pa_id=self.pa.id)
        cmd_mark_filed(pa_id=self.pa.id)
        cmd_start_ack_reconciling(pa_id=self.pa.id)
        pa = cmd_close(pa_id=self.pa.id)
        self.assertEqual(pa.lifecycle_state, LifecycleState.CLOSED)

    def test_reject_path(self):
        cmd_enter_clearing(pa_id=self.pa.id)
        self._make_pa_ready_for_clearing()
        cmd_complete_clearing(pa_id=self.pa.id)
        cmd_confirm_payment_received(pa_id=self.pa.id)
        cmd_mark_ready_for_review(pa_id=self.pa.id)
        cmd_start_review(pa_id=self.pa.id)
        cmd_mark_filed(pa_id=self.pa.id)
        cmd_start_ack_reconciling(pa_id=self.pa.id)
        pa = cmd_set_pending_reject_correction(pa_id=self.pa.id)
        self.assertEqual(pa.lifecycle_state, LifecycleState.PENDING_REJECT_CORRECTION)

    def test_illegal_transition_raises(self):
        cmd_enter_clearing(pa_id=self.pa.id)
        with self.assertRaises(ValidationError):
            cmd_mark_filed(pa_id=self.pa.id)

    def test_is_complete_not_set_by_lifecycle(self):
        cmd_enter_clearing(pa_id=self.pa.id)
        self._make_pa_ready_for_clearing()
        cmd_complete_clearing(pa_id=self.pa.id)
        self.pa.refresh_from_db()
        self.assertFalse(self.pa.is_complete)

    def test_complete_clearing_requires_validation_fields(self):
        cmd_enter_clearing(pa_id=self.pa.id)
        with self.assertRaises(ValidationError):
            cmd_complete_clearing(pa_id=self.pa.id)

    def test_reopen_clearing_from_clearing_complete(self):
        cmd_enter_clearing(pa_id=self.pa.id)
        self._make_pa_ready_for_clearing()
        cmd_complete_clearing(pa_id=self.pa.id)
        pa = cmd_reopen_clearing(pa_id=self.pa.id, confirmed_fee="100.00")
        self.assertEqual(pa.lifecycle_state, LifecycleState.IN_CLEARING)

    def test_cancel_assignment_from_in_clearing(self):
        cmd_enter_clearing(pa_id=self.pa.id)
        pa = cmd_cancel_assignment(
            pa_id=self.pa.id,
            actor=self.preparer,
            cancellation_reason="Client withdrew",
        )
        self.assertEqual(pa.lifecycle_state, LifecycleState.CANCELLED)
        self.assertFalse(pa.is_active)
        self.assertEqual(pa.cancellation_reason, "Client withdrew")
        self.assertIsNotNone(pa.cancelled_at)
        self.assertTrue(
            ProductAssignmentEvent.objects.filter(
                product_assignment=pa,
                event_type=ProductAssignmentEvent.EventType.ASSIGNMENT_CANCELLED,
            ).exists()
        )
        self.assertTrue(
            LifecycleTransition.objects.filter(
                product_assignment=pa,
                to_state=LifecycleState.CANCELLED,
            ).exists()
        )

    def test_cancel_assignment_requires_reason(self):
        cmd_enter_clearing(pa_id=self.pa.id)
        with self.assertRaises(ValidationError):
            cmd_cancel_assignment(pa_id=self.pa.id, cancellation_reason="   ")

    def test_cancel_assignment_blocked_after_clearing_complete(self):
        cmd_enter_clearing(pa_id=self.pa.id)
        self._make_pa_ready_for_clearing()
        cmd_complete_clearing(pa_id=self.pa.id)
        with self.assertRaises(ValidationError):
            cmd_cancel_assignment(
                pa_id=self.pa.id,
                cancellation_reason="Too late",
            )
