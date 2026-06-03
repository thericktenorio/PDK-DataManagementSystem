"""Phase 9 warehouse ETL tests (dual-database).

Run with:
  DJANGO_TEST_DUAL_ANALYTICS=1 python manage.py test analytics.tests.test_etl
"""
import uuid
from decimal import Decimal

from django.test import TransactionTestCase

from analytics.models import EtlRun, FactAssignment, FactInvoice
from analytics.services.etl import _resolve_revenue, run_analytics_etl
from billing.models import AssignmentInvoiceLink, Invoice
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
from core.workflows.lifecycle import cmd_complete_clearing, cmd_enter_clearing
from accounts.models import InternalUser


class AnalyticsEtlTests(TransactionTestCase):
    databases = {"default", "analytics"}

    def setUp(self):
        self.org = Organization.objects.create(name=f"Org-{uuid.uuid4().hex[:6]}")
        self.preparer = InternalUser.objects.create_user(
            email=f"prep-{uuid.uuid4().hex[:8]}@example.com",
            password="test-pass-123",
            organization=self.org,
            role="tax_preparer",
        )
        self.season = TaxSeason.objects.create(
            year=2099,
            start_date="2099-01-01",
            end_date="2099-12-31",
            is_active=True,
        )
        self.client = Client.objects.create(
            name="Analytics Test Client",
            TIN="123456789",
            email="client@example.com",
        )
        self.tax_year = TaxYear.objects.create(client=self.client, year=2098, balance=0)
        self.product = Product.objects.create(
            tax_year=self.tax_year,
            product_type=Product.PRODUCT_TYPE_PERSONAL_TAXES,
            is_product_active=True,
            default_price=Decimal("400.00"),
        )
        self.intake = Intake.objects.create(
            client=self.client,
            tax_season=self.season,
            is_active=True,
        )
        self.filing_type = FilingType.objects.create(
            filing_type=FilingType.FILING_TYPE_SIMPLE,
        )

    def _make_pa(self, *, fee="350.00", payment_method=ProductAssignment.PAYMENT_METHOD_QBO):
        pa, _created = ProductAssignment.objects.create_product_assignment(
            client=self.client,
            intake=self.intake,
            tax_year=self.tax_year,
            filing_type=self.filing_type,
            product=self.product,
            preparer=self.preparer,
            is_active=True,
            fee=Decimal(fee),
            payment_method=payment_method,
            closing_message_text="Your return is ready for review.",
        )
        cmd_enter_clearing(pa_id=pa.id, actor=self.preparer)
        cmd_complete_clearing(pa_id=pa.id, actor=self.preparer)
        pa.refresh_from_db()
        return pa

    def test_etl_full_populates_assignment_and_dual_revenue(self):
        pa = self._make_pa()
        invoice = Invoice.objects.create(
            client=self.client,
            status=Invoice.INVOICE_STATUS_PAID,
            qbo_amount_cents=35000,
            qbo_balance_cents=0,
        )
        AssignmentInvoiceLink.objects.create(product_assignment=pa, invoice=invoice)

        run = run_analytics_etl(full=True)
        self.assertEqual(run.status, EtlRun.Status.SUCCESS)
        self.assertGreater(run.rows_assignments, 0)

        fact = FactAssignment.objects.using("analytics").get(source_pa_id=pa.id)
        self.assertEqual(fact.expected_fee, Decimal("350.00"))
        self.assertEqual(fact.invoice_paid_amount, Decimal("350.00"))
        self.assertEqual(fact.actual_revenue_recognized, Decimal("350.00"))
        self.assertEqual(fact.lifecycle_state, LifecycleState.CLEARING_COMPLETE)

        inv_fact = FactInvoice.objects.using("analytics").get(source_invoice_id=invoice.id)
        self.assertTrue(inv_fact.is_paid)

    def test_resolve_revenue_non_qbo_cash(self):
        actual, paid_at, gap = _resolve_revenue(
            payment_method=ProductAssignment.PAYMENT_METHOD_CASH,
            expected_fee=Decimal("200.00"),
            expected_fee_at=None,
            clearing_complete_at=None,
            ready_for_review_at=None,
            invoice=None,
        )
        self.assertIsNone(actual)

        from django.utils import timezone

        now = timezone.now()
        actual, paid_at, gap = _resolve_revenue(
            payment_method=ProductAssignment.PAYMENT_METHOD_CASH,
            expected_fee=Decimal("200.00"),
            expected_fee_at=now,
            clearing_complete_at=now,
            ready_for_review_at=None,
            invoice=None,
        )
        self.assertEqual(actual, Decimal("200.00"))
        self.assertIsNotNone(paid_at)
        self.assertEqual(gap, Decimal("0.00"))
