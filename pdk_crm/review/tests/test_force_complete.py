"""Force completion tests (W5)."""
import datetime
import uuid
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from acknowledgments.selectors import build_clearing_status_columns, compute_tp_comp_date
from core.models import (
    Acknowledgment,
    Client,
    FilingType,
    Intake,
    LifecycleState,
    Organization,
    Product,
    ProductAssignment,
    TaxSeason,
    TaxYear,
)
from acknowledgments.services.reconcile import evaluate_pa_lifecycle_after_ack_change
from core.workflows.lifecycle import (
    cmd_complete_clearing,
    cmd_confirm_payment_received,
    cmd_enter_clearing,
    cmd_mark_filed,
    cmd_start_ack_reconciling,
)
from review.selectors import review_table_queryset
from review.services.force_complete import force_complete_review_for_pa

User = get_user_model()


class ForceCompleteTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name=f"Org {uuid.uuid4().hex[:8]}")
        self.user = User.objects.create_user(
            email=f"prep-{uuid.uuid4().hex[:8]}@example.com",
            password="testpass123",
            organization=self.org,
            role="tax_preparer",
        )
        self.reviewer = User.objects.create_user(
            email=f"rev-{uuid.uuid4().hex[:8]}@example.com",
            password="testpass123",
            organization=self.org,
            role="reviewer",
        )
        self.client_obj = Client.objects.create(TIN="987654321", name="Force Client")
        self.season = TaxSeason.objects.create(
            year=2025,
            start_date=datetime.date(2025, 1, 1),
            end_date=datetime.date(2025, 10, 15),
            is_active=True,
        )
        self.tax_year = TaxYear.objects.create(client=self.client_obj, year=2024)
        self.filing_type = FilingType.objects.get_or_create(
            filing_type=FilingType.FILING_TYPE_SIMPLE
        )[0]
        self.product = Product.objects.create(
            tax_year=self.tax_year,
            product_type=Product.PRODUCT_TYPE_PERSONAL_TAXES,
            default_price=Decimal("100.00"),
        )
        self.intake = Intake.objects.create(
            client=self.client_obj,
            tax_season=self.season,
            is_active=True,
        )
        self.pa = ProductAssignment.objects.create(
            client=self.client_obj,
            intake=self.intake,
            tax_year=self.tax_year,
            product=self.product,
            filing_type=self.filing_type,
            is_active=True,
            lifecycle_state=LifecycleState.IN_CLEARING,
            fee=Decimal("100.00"),
            payment_method=ProductAssignment.PAYMENT_METHOD_CASH,
            preparer=self.user,
            closing_message_text="Ready",
            expected_ack_count=1,
        )

    def _file_with_reject(self):
        cmd_enter_clearing(pa_id=self.pa.id)
        cmd_complete_clearing(pa_id=self.pa.id)
        cmd_confirm_payment_received(pa_id=self.pa.id)
        cmd_mark_filed(pa_id=self.pa.id, expected_ack_count=1)
        cmd_start_ack_reconciling(pa_id=self.pa.id)
        Acknowledgment.objects.create(
            product_assignment=self.pa,
            product=self.product,
            tax_season=self.season,
            type="1040",
            status="R",
            date=datetime.date(2025, 3, 1),
            year=2024,
            client_tin="987654321",
            client_name="Force Client",
        )
        evaluate_pa_lifecycle_after_ack_change(pa_id=self.pa.id)
        self.pa.refresh_from_db()

    def test_force_complete_moves_to_closed_with_tp_comp(self):
        self._file_with_reject()
        self.assertEqual(self.pa.lifecycle_state, LifecycleState.PENDING_REJECT_CORRECTION)
        self.assertIsNone(compute_tp_comp_date(self.pa))

        pa, _entry = force_complete_review_for_pa(
            pa_id=self.pa.id,
            actor=self.reviewer,
            note="Extension client; accept perpetual R",
        )
        pa.refresh_from_db()

        self.assertEqual(pa.lifecycle_state, LifecycleState.CLOSED)
        self.assertIsNotNone(pa.force_completed_at)
        self.assertEqual(review_table_queryset(table="filed").filter(id=pa.id).count(), 1)

        tp_comp = compute_tp_comp_date(pa)
        self.assertIsNotNone(tp_comp)
        self.assertEqual(tp_comp.weekday(), 6)

        cols = build_clearing_status_columns(pa)
        self.assertIn("Forced", cols["fed_status"])
        self.assertNotEqual(cols["tp_comp_dt"], "—")

    def test_force_complete_requires_note(self):
        self._file_with_reject()
        from django.core.exceptions import ValidationError
        from core.workflows.lifecycle import cmd_force_complete_review

        with self.assertRaises(ValidationError):
            cmd_force_complete_review(pa_id=self.pa.id, actor=self.reviewer, note="")
