"""Review integration — parser-derived expected ack count at Review Complete."""
import datetime
import uuid
from decimal import Decimal

from django.test import TestCase

from core.models import (
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
from core.workflows.lifecycle import (
    cmd_complete_clearing,
    cmd_confirm_payment_received,
    cmd_enter_clearing,
)
from clearing.services.parser_schema import (
    build_parse_result_snapshot,
    suggested_expected_ack_count,
)
from review.selectors import build_review_row

from accounts.models import InternalUser


class ParserAckHintReviewTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name=f"Org {uuid.uuid4().hex[:8]}")
        self.preparer = InternalUser.objects.create_user(
            email=f"prep-{uuid.uuid4().hex[:8]}@example.com",
            password="testpass123",
            organization=self.org,
            role="tax_preparer",
        )
        self.client_obj = Client.objects.create(TIN="123456789", name="Ack Hint Client")
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
        self.filing_type = FilingType.objects.create(filing_type=FilingType.FILING_TYPE_DEFAULT)
        self.product = Product.objects.create(
            tax_year=self.tax_year,
            product_type=Product.PRODUCT_TYPE_DEFAULT,
            default_price=Decimal("250.00"),
        )
        self.pa = ProductAssignment.objects.create(
            client=self.client_obj,
            intake=self.intake,
            tax_year=self.tax_year,
            product=self.product,
            filing_type=self.filing_type,
            preparer=self.preparer,
            payment_method=ProductAssignment.PAYMENT_METHOD_CASH,
            fee=Decimal("250.00"),
            closing_message_text="Thanks.",
            is_active=True,
            lifecycle_state=LifecycleState.IN_CLEARING,
        )

    def _advance_to_ready_for_review(self):
        cmd_enter_clearing(pa_id=self.pa.id)
        cmd_complete_clearing(pa_id=self.pa.id)
        cmd_confirm_payment_received(pa_id=self.pa.id)
        self.pa.refresh_from_db()

    def test_suggested_expected_ack_count_from_parse_snapshot(self):
        snapshot = build_parse_result_snapshot(
            job_id=uuid.uuid4(),
            detail={
                "fields": {
                    "taxpayer_first_name": "Jane",
                    "tax_year": "2024",
                    "expected_ack_count": 3,
                    "expected_transmissions": [
                        {"jurisdiction": "federal", "form_type": "1040", "source": "client_letter"},
                        {"jurisdiction": "state", "form_type": "CA540", "source": "client_letter"},
                        {"jurisdiction": "state", "form_type": "HIN15", "source": "diagnostic"},
                    ],
                    "message_ready": True,
                },
                "message": "Hi Jane",
            },
        )
        self.pa.parse_result_json = snapshot
        self.pa.save(update_fields=["parse_result_json"])

        self.assertEqual(suggested_expected_ack_count(self.pa), 3)

    def test_build_review_row_includes_parser_suggestion(self):
        self._advance_to_ready_for_review()
        self.pa.parse_result_json = build_parse_result_snapshot(
            job_id=uuid.uuid4(),
            detail={
                "fields": {
                    "expected_ack_count": 2,
                    "message_ready": True,
                },
            },
        )
        self.pa.save(update_fields=["parse_result_json"])

        row = build_review_row(self.pa)
        self.assertEqual(row["suggested_expected_ack_count"], 2)

    def test_no_suggestion_without_parser_hint(self):
        self._advance_to_ready_for_review()
        row = build_review_row(self.pa)
        self.assertIsNone(row["suggested_expected_ack_count"])
