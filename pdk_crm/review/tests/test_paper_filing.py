"""Paper filing tests (W5)."""
import datetime
import uuid
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from acknowledgments.selectors import compute_tp_comp_date
from core.models import (
    Acknowledgment,
    Client,
    FilingType,
    Intake,
    LifecycleState,
    Organization,
    PaperFilingDetail,
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
from review.selectors import review_table_queryset
from review.services.paper_filing import record_paper_filing

User = get_user_model()


class PaperFilingTests(TestCase):
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
        self.client_obj = Client.objects.create(TIN="111222333", name="Paper Client")
        self.season = TaxSeason.objects.create(
            year=2025,
            start_date=datetime.date(2025, 1, 1),
            end_date=datetime.date(2025, 10, 15),
            is_active=True,
        )
        self.tax_year = TaxYear.objects.create(client=self.client_obj, year=2020)
        self.filing_type = FilingType.objects.get_or_create(
            filing_type=FilingType.FILING_TYPE_SIMPLE
        )[0]
        self.product = Product.objects.create(
            tax_year=self.tax_year,
            product_type=Product.PRODUCT_TYPE_PERSONAL_TAXES,
            default_price=Decimal("100.00"),
        )
        Product.objects.create(
            tax_year=self.tax_year,
            product_type=Product.PRODUCT_TYPE_PAPER_FILING,
            default_price=Decimal("0.00"),
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

    def _advance_to_ready(self):
        cmd_enter_clearing(pa_id=self.pa.id)
        cmd_complete_clearing(pa_id=self.pa.id)
        cmd_confirm_payment_received(pa_id=self.pa.id)
        self.pa.refresh_from_db()

    def test_paper_file_creates_acks_and_tp_comp(self):
        self._advance_to_ready()
        pa = record_paper_filing(
            pa_id=self.pa.id,
            filings=[
                {
                    "jurisdiction": "federal",
                    "form_type": "1040",
                    "mailed_by": "firm",
                    "sent_date": "2020-04-10",
                    "tracking": "USPS999",
                    "notes": "Mailed at post office",
                }
            ],
            actor=self.reviewer,
        )
        pa.refresh_from_db()

        self.assertEqual(pa.product.product_type, Product.PRODUCT_TYPE_PAPER_FILING)
        self.assertEqual(pa.lifecycle_state, LifecycleState.CLOSED)
        self.assertEqual(PaperFilingDetail.objects.filter(product_assignment=pa).count(), 1)

        acks = list(pa.acknowledgments.all())
        self.assertEqual(len(acks), 1)
        self.assertEqual(acks[0].status, Acknowledgment.STATUS_PAPER_FILED)
        self.assertEqual(acks[0].date, datetime.date(2020, 4, 10))

        tp_comp = compute_tp_comp_date(pa)
        self.assertEqual(tp_comp, datetime.date(2020, 4, 12))  # Sunday after Apr 10
        self.assertEqual(review_table_queryset(table="filed").filter(id=pa.id).count(), 1)
