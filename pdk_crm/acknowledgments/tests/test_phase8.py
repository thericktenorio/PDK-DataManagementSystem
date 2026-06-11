"""Acknowledgments Phase 8 tests."""
import datetime
import uuid
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from acknowledgments.services.reconcile import ingest_ack_records, normalize_ack_status
from acknowledgments.selectors import build_pa_ack_summary
from core.models import (
    AckStaging,
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
from acknowledgments.views import _parse_ack_text
from core.workflows.lifecycle import (
    cmd_complete_clearing,
    cmd_confirm_payment_received,
    cmd_enter_clearing,
    cmd_mark_filed,
    cmd_start_ack_reconciling,
)

User = get_user_model()


class Phase8AckTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name=f"Org {uuid.uuid4().hex[:8]}")
        self.user = User.objects.create_user(
            email=f"staff-{uuid.uuid4().hex[:8]}@example.com",
            password="testpass123",
            organization=self.org,
            role="tax_preparer",
        )
        self.client_obj = Client.objects.create(TIN="123456789", name="Ack Client")
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
        )

    def _file_pa(self, expected_ack_count=2):
        cmd_enter_clearing(pa_id=self.pa.id)
        cmd_complete_clearing(pa_id=self.pa.id)
        cmd_confirm_payment_received(pa_id=self.pa.id)
        cmd_mark_filed(pa_id=self.pa.id, expected_ack_count=expected_ack_count)
        self.pa.refresh_from_db()

    def test_normalize_ack_status(self):
        self.assertEqual(normalize_ack_status("A"), Acknowledgment.STATUS_ACCEPTED)
        self.assertEqual(normalize_ack_status("R"), Acknowledgment.STATUS_REJECTED)

    def test_ingest_moves_filed_pa_to_ack_reconciling(self):
        self._file_pa(expected_ack_count=1)
        records = [
            {
                "client_tin": "123456789",
                "type": "1040",
                "status": "A",
                "date": datetime.date(2025, 3, 1),
                "client_name": "Ack Client",
                "year": 2024,
            }
        ]
        result = ingest_ack_records(records, active_season=self.season, actor=self.user)
        self.assertEqual(result["created"], 1)
        self.pa.refresh_from_db()
        self.assertEqual(self.pa.lifecycle_state, LifecycleState.CLOSED)

    def test_reject_transitions_to_pending_reject_correction(self):
        self._file_pa(expected_ack_count=1)
        records = [
            {
                "client_tin": "123456789",
                "type": "1040",
                "status": "R",
                "date": datetime.date(2025, 3, 1),
                "client_name": "Ack Client",
                "year": 2024,
            }
        ]
        ingest_ack_records(records, active_season=self.season, actor=self.user)
        self.pa.refresh_from_db()
        self.assertEqual(self.pa.lifecycle_state, LifecycleState.PENDING_REJECT_CORRECTION)

    def test_acceptance_after_reject_returns_to_reconciling(self):
        self._file_pa(expected_ack_count=1)
        ingest_ack_records(
            [
                {
                    "client_tin": "123456789",
                    "type": "1040",
                    "status": "R",
                    "date": datetime.date(2025, 3, 1),
                    "client_name": "Ack Client",
                    "year": 2024,
                }
            ],
            active_season=self.season,
            actor=self.user,
        )
        ingest_ack_records(
            [
                {
                    "client_tin": "123456789",
                    "type": "1040",
                    "status": "A",
                    "date": datetime.date(2025, 3, 1),
                    "client_name": "Ack Client",
                    "year": 2024,
                }
            ],
            active_season=self.season,
            actor=self.user,
        )
        self.pa.refresh_from_db()
        self.assertEqual(self.pa.lifecycle_state, LifecycleState.CLOSED)

    def test_unmatched_ack_staged_when_pa_not_filed(self):
        records = [
            {
                "client_tin": "123456789",
                "type": "1040",
                "status": "A",
                "date": datetime.date(2025, 3, 1),
                "client_name": "Ack Client",
                "year": 2024,
            }
        ]
        result = ingest_ack_records(records, active_season=self.season, actor=self.user)
        self.assertEqual(len(result["unmatched"]), 1)
        self.assertTrue(AckStaging.objects.filter(client_tin="123456789").exists())

    def test_multi_ack_close_requires_expected_count(self):
        self._file_pa(expected_ack_count=2)
        ingest_ack_records(
            [
                {
                    "client_tin": "123456789",
                    "type": "1040",
                    "status": "A",
                    "date": datetime.date(2025, 3, 1),
                    "client_name": "Ack Client",
                    "year": 2024,
                }
            ],
            active_season=self.season,
            actor=self.user,
        )
        self.pa.refresh_from_db()
        self.assertEqual(self.pa.lifecycle_state, LifecycleState.ACK_RECONCILING)

        ingest_ack_records(
            [
                {
                    "client_tin": "123456789",
                    "type": "CA540",
                    "status": "A",
                    "date": datetime.date(2025, 3, 2),
                    "client_name": "Ack Client",
                    "year": 2024,
                }
            ],
            active_season=self.season,
            actor=self.user,
        )
        self.pa.refresh_from_db()
        self.assertEqual(self.pa.lifecycle_state, LifecycleState.CLOSED)

    def test_ack_summary_badge(self):
        self._file_pa(expected_ack_count=2)
        cmd_start_ack_reconciling(pa_id=self.pa.id)
        Acknowledgment.objects.create(
            product_assignment=self.pa,
            product=self.product,
            tax_season=self.season,
            type="1040",
            status=Acknowledgment.STATUS_ACCEPTED,
            date=datetime.date(2025, 3, 1),
            year=2024,
            client_tin="123456789",
            client_name="Ack Client",
        )
        summary = build_pa_ack_summary(self.pa)
        self.assertEqual(summary["accepted_count"], 1)
        self.assertEqual(summary["badge_text"], "1/2")
        self.assertEqual(summary["badge_class"], "ack-badge-progress")

    def test_safety_net_auto_advances_ready_for_review(self):
        cmd_enter_clearing(pa_id=self.pa.id)
        cmd_complete_clearing(pa_id=self.pa.id)
        cmd_confirm_payment_received(pa_id=self.pa.id)
        self.pa.refresh_from_db()
        self.assertEqual(self.pa.lifecycle_state, LifecycleState.READY_FOR_REVIEW)

        records = [
            {
                "client_tin": "123456789",
                "type": "1040",
                "status": "A",
                "date": datetime.date(2025, 3, 1),
                "client_name": "Ack Client",
                "year": 2024,
            }
        ]
        result = ingest_ack_records(records, active_season=self.season, actor=self.user)
        self.assertEqual(result["created"], 1)
        self.pa.refresh_from_db()
        self.assertEqual(self.pa.lifecycle_state, LifecycleState.CLOSED)
        self.assertEqual(self.pa.expected_ack_count, 1)

    def test_drake_mef_parser_submission_and_error_detail(self):
        raw = (
            "Drake 2024 - MEF ACK files processed\n"
            "IDNumber   Type      Acc  Date          Name                                     Reject Codes\n"
            "000000005  1040      R    11-02-2025    CLIENT 5, TEST                           IND-181-01\n"
            "SubmissionId:  3387962025306aifuwko\n"
            "\n"
            "                                                    Error Detail\n"
            "IDNumber      Rule #               Message\n"
            "000000005     IND-181-01           The Primary Taxpayer did not enter a valid Identity Protection Personal\n"
        )
        records, err = _parse_ack_text(raw)
        self.assertIsNone(err)
        self.assertEqual(len(records), 1)
        rec = records[0]
        self.assertEqual(rec["client_tin"], "000000005")
        self.assertEqual(rec["reject_code"], "IND-181-01")
        self.assertEqual(rec["submission_id"], "3387962025306aifuwko")
        self.assertIn("Identity Protection", rec["reject_reason"])

    def test_post_acknowledgments_endpoint(self):
        self._file_pa(expected_ack_count=1)
        self.client.force_login(self.user)
        raw = (
            "Drake 2024 - Federal/State MEF ACK files processed\n"
            "IDNumber    Type    Acc Date        Name        Reject Codes\n"
            "123456789   1040    A   03-01-2025  ACK CLIENT\n"
        )
        resp = self.client.post(
            reverse("acknowledgments:post"),
            {"pasted_data": raw},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "success")
        self.pa.refresh_from_db()
        self.assertEqual(self.pa.lifecycle_state, LifecycleState.CLOSED)
