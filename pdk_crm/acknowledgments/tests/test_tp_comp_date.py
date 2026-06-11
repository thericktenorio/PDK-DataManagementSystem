"""TP Comp Dt and clearing status column tests (W4)."""
import datetime
import uuid
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from acknowledgments.selectors import (
    build_clearing_status_columns,
    compute_tp_comp_date,
    format_tp_comp_tooltip,
)
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
    cmd_force_complete_review,
    cmd_mark_filed,
    cmd_start_ack_reconciling,
)

User = get_user_model()


class TPCompDateTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name=f"Org {uuid.uuid4().hex[:8]}")
        self.user = User.objects.create_user(
            email=f"staff-{uuid.uuid4().hex[:8]}@example.com",
            password="testpass123",
            organization=self.org,
            role="tax_preparer",
        )
        self.client_obj = Client.objects.create(TIN="123456789", name="TP Comp Client")
        self.season = TaxSeason.objects.create(
            year=2024,
            start_date=datetime.date(2024, 1, 1),
            end_date=datetime.date(2024, 10, 15),
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
            expected_ack_count=2,
        )

    def _file_pa(self):
        cmd_enter_clearing(pa_id=self.pa.id)
        cmd_complete_clearing(pa_id=self.pa.id)
        cmd_confirm_payment_received(pa_id=self.pa.id)
        cmd_mark_filed(pa_id=self.pa.id, expected_ack_count=2)
        self.pa.refresh_from_db()

    def _create_ack(self, *, form_type: str, ack_date: datetime.date, status: str = "A"):
        Acknowledgment.objects.create(
            product_assignment=self.pa,
            product=self.product,
            tax_season=self.season,
            type=form_type,
            status=status,
            date=ack_date,
            year=2024,
            client_tin="123456789",
            client_name="TP Comp Client",
        )

    def test_blank_when_not_all_expected_acks(self):
        self._file_pa()
        self._create_ack(form_type="1040", ack_date=datetime.date(2025, 3, 1))
        self.assertIsNone(compute_tp_comp_date(self.pa))

    def test_blank_when_any_reject(self):
        self._file_pa()
        self._create_ack(form_type="1040", ack_date=datetime.date(2025, 3, 1), status="A")
        self._create_ack(form_type="CA540", ack_date=datetime.date(2025, 3, 2), status="R")
        self.assertIsNone(compute_tp_comp_date(self.pa))

    def test_sunday_after_weekday_landmark(self):
        self._file_pa()
        # Friday 2025-11-07 → Sunday 2025-11-09
        self._create_ack(form_type="1040", ack_date=datetime.date(2025, 11, 7))
        self._create_ack(form_type="CA540", ack_date=datetime.date(2025, 11, 5))
        result = compute_tp_comp_date(self.pa)
        self.assertEqual(result, datetime.date(2025, 11, 9))

    def test_sunday_landmark_uses_following_sunday(self):
        self._file_pa()
        # Sunday 2025-11-09 → following Sunday 2025-11-16
        self._create_ack(form_type="1040", ack_date=datetime.date(2025, 11, 9))
        self._create_ack(form_type="CA540", ack_date=datetime.date(2025, 11, 3))
        result = compute_tp_comp_date(self.pa)
        self.assertEqual(result, datetime.date(2025, 11, 16))

    def test_paper_filed_counts_as_compensating(self):
        self._file_pa()
        self._create_ack(form_type="1040", ack_date=datetime.date(2025, 3, 3))
        Acknowledgment.objects.create(
            product_assignment=self.pa,
            product=self.product,
            tax_season=self.season,
            type="CA540",
            status=Acknowledgment.STATUS_PAPER_FILED,
            date=datetime.date(2025, 3, 1),
            year=2024,
            client_tin="123456789",
            client_name="TP Comp Client",
        )
        result = compute_tp_comp_date(self.pa)
        self.assertEqual(result, datetime.date(2025, 3, 9))

    def test_tp_comp_tooltip_includes_tz_abbrev(self):
        comp = datetime.date(2025, 11, 9)
        tooltip = format_tp_comp_tooltip(comp)
        self.assertTrue(tooltip.startswith("2025-11-09 "))
        self.assertIn(tooltip.split()[-1], {"PST", "PDT"})

    def test_clearing_status_columns_all_a_gate(self):
        self._file_pa()
        self._create_ack(form_type="1040", ack_date=datetime.date(2025, 11, 7))
        self._create_ack(form_type="CA540", ack_date=datetime.date(2025, 11, 5))
        cols = build_clearing_status_columns(self.pa)
        self.assertEqual(cols["fed_status"], "A")
        self.assertEqual(cols["st_status"], "A")
        self.assertEqual(cols["tp_comp_dt"], "2025-11-09")
        self.assertTrue(cols["tp_comp_tooltip"])

    def test_clearing_status_blank_tp_comp_when_incomplete(self):
        self._file_pa()
        self._create_ack(form_type="1040", ack_date=datetime.date(2025, 11, 7))
        cols = build_clearing_status_columns(self.pa)
        self.assertEqual(cols["tp_comp_dt"], "—")
        self.assertEqual(cols["tp_comp_tooltip"], "")

    def test_force_complete_counts_as_compensating_with_mixed_a(self):
        self._file_pa()
        cmd_start_ack_reconciling(pa_id=self.pa.id)
        self._create_ack(form_type="1040", ack_date=datetime.date(2025, 11, 5), status="A")
        self._create_ack(form_type="CA540", ack_date=datetime.date(2025, 11, 3), status="R")
        evaluate_pa_lifecycle_after_ack_change(pa_id=self.pa.id)
        self.pa.refresh_from_db()
        cmd_force_complete_review(
            pa_id=self.pa.id,
            actor=self.user,
            note="Perpetual extension reject",
        )
        self.pa.refresh_from_db()
        result = compute_tp_comp_date(self.pa)
        self.assertIsNotNone(result)
        self.assertEqual(result.weekday(), 6)
        cols = build_clearing_status_columns(self.pa)
        self.assertIn("Forced", cols["st_status"])
        self.assertNotEqual(cols["tp_comp_dt"], "—")
