"""Billing Phase 6 tests."""
import datetime
import uuid
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from billing.models import AssignmentInvoiceLink, Invoice
from billing.services.invoice_lifecycle import advance_pas_when_invoice_paid, advance_pas_when_invoice_sent
from billing.services.post_clearing import on_clearing_completed
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
    cmd_reopen_clearing,
    target_state_after_clearing_complete,
)

User = get_user_model()


class BillingPhase6Tests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name=f"Org {uuid.uuid4().hex[:8]}")
        self.preparer = User.objects.create_user(
            email=f"prep-{uuid.uuid4().hex[:8]}@example.com",
            password="testpass123",
            organization=self.org,
            role="tax_preparer",
        )
        self.client_obj = Client.objects.create(TIN="123456789", name="Billing Test Client")
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

    def _make_pa(self, *, payment_method=ProductAssignment.PAYMENT_METHOD_CASH):
        pa = ProductAssignment.objects.create(
            client=self.client_obj,
            intake=self.intake,
            tax_year=self.tax_year,
            product=self.product,
            filing_type=self.filing_type,
            is_active=True,
            payment_method=payment_method,
            fee=Decimal("100.00"),
            preparer=self.preparer,
            closing_message_text="Ready.",
        )
        cmd_enter_clearing(pa_id=pa.id, actor=self.preparer)
        return pa

    def _complete(self, pa):
        cmd_complete_clearing(pa_id=pa.id, actor=self.preparer)
        on_clearing_completed(pa_id=pa.id, actor=self.preparer)
        pa.refresh_from_db()
        return pa

    def test_qbo_clears_to_draft_not_awaiting_payment(self):
        pa = self._make_pa(payment_method=ProductAssignment.PAYMENT_METHOD_QBO)
        pa = self._complete(pa)
        self.assertEqual(pa.lifecycle_state, LifecycleState.CLEARING_COMPLETE)
        self.assertTrue(AssignmentInvoiceLink.objects.filter(product_assignment=pa).exists())
        self.assertEqual(
            target_state_after_clearing_complete(pa),
            LifecycleState.CLEARING_COMPLETE,
        )

    def test_no_fee_auto_advances_to_review(self):
        pa = self._make_pa(payment_method=ProductAssignment.PAYMENT_METHOD_NO_FEE_PRO_BONO)
        pa = self._complete(pa)
        self.assertEqual(pa.lifecycle_state, LifecycleState.READY_FOR_REVIEW)

    def test_cash_stays_until_confirm_payment(self):
        pa = self._make_pa(payment_method=ProductAssignment.PAYMENT_METHOD_CASH)
        pa = self._complete(pa)
        self.assertEqual(pa.lifecycle_state, LifecycleState.CLEARING_COMPLETE)
        pa = cmd_confirm_payment_received(pa_id=pa.id, actor=self.preparer)
        self.assertEqual(pa.lifecycle_state, LifecycleState.READY_FOR_REVIEW)

    def test_invoice_sent_advances_qbo_to_awaiting_payment(self):
        pa = self._make_pa(payment_method=ProductAssignment.PAYMENT_METHOD_QBO)
        pa = self._complete(pa)
        inv = pa.invoice_link.invoice
        inv.status = Invoice.INVOICE_STATUS_SENT
        inv.qbo_invoice_id = "TEST-123"
        inv.save()
        advance_pas_when_invoice_sent(inv, [pa], actor=self.preparer)
        pa.refresh_from_db()
        self.assertEqual(pa.lifecycle_state, LifecycleState.AWAITING_PAYMENT)

    def test_invoice_paid_advances_to_ready_for_review(self):
        pa = self._make_pa(payment_method=ProductAssignment.PAYMENT_METHOD_QBO)
        pa = self._complete(pa)
        inv = pa.invoice_link.invoice
        inv.status = Invoice.INVOICE_STATUS_SENT
        inv.qbo_invoice_id = "TEST-456"
        inv.save()
        advance_pas_when_invoice_sent(inv, [pa], actor=self.preparer)
        inv.qbo_amount_cents = 10000
        inv.qbo_balance_cents = 0
        inv.status = Invoice.INVOICE_STATUS_PAID
        inv.save()
        advance_pas_when_invoice_paid(inv, actor=self.preparer)
        pa.refresh_from_db()
        self.assertEqual(pa.lifecycle_state, LifecycleState.READY_FOR_REVIEW)

    def test_reopen_from_awaiting_payment_requires_acknowledgement(self):
        pa = self._make_pa(payment_method=ProductAssignment.PAYMENT_METHOD_QBO)
        pa = self._complete(pa)
        inv = pa.invoice_link.invoice
        inv.status = Invoice.INVOICE_STATUS_SENT
        inv.qbo_invoice_id = "TEST-789"
        inv.save()
        advance_pas_when_invoice_sent(inv, [pa], actor=self.preparer)
        with self.assertRaises(Exception):
            cmd_reopen_clearing(
                pa_id=pa.id,
                actor=self.preparer,
                confirmed_fee="100.00",
                acknowledge_invoice_sent=False,
            )
        pa = cmd_reopen_clearing(
            pa_id=pa.id,
            actor=self.preparer,
            confirmed_fee="100.00",
            acknowledge_invoice_sent=True,
        )
        self.assertEqual(pa.lifecycle_state, LifecycleState.IN_CLEARING)
