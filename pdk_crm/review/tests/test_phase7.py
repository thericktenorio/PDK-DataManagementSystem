"""Review Phase 7 tests."""
import datetime
import uuid
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client as DjangoClient, TestCase
from django.urls import reverse

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
from core.workflows.lifecycle import (
    cmd_complete_clearing,
    cmd_confirm_payment_received,
    cmd_enter_clearing,
    cmd_mark_ready_for_review,
)
from review.models import ReviewEntry
from review.selectors import payment_status_label, review_queue_count
from review.services.queue import mark_filed_for_pa, start_review_for_pa

User = get_user_model()


class ReviewPhase7Tests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name=f"Org {uuid.uuid4().hex[:8]}")
        self.preparer = User.objects.create_user(
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
        self.denied_user = User.objects.create_user(
            email=f"deny-{uuid.uuid4().hex[:8]}@example.com",
            password="testpass123",
            organization=self.org,
            role="office_admin",
        )
        self.client_obj = Client.objects.create(TIN="123456789", name="Review Test Client")
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
            closing_message_text="Thanks for your business.",
            is_active=True,
            lifecycle_state=LifecycleState.IN_CLEARING,
        )

    def _advance_to_ready_for_review(self):
        cmd_enter_clearing(pa_id=self.pa.id)
        cmd_complete_clearing(pa_id=self.pa.id)
        cmd_confirm_payment_received(pa_id=self.pa.id)
        self.pa.refresh_from_db()
        self.assertEqual(self.pa.lifecycle_state, LifecycleState.READY_FOR_REVIEW)

    def test_review_entry_created_on_start_review(self):
        self._advance_to_ready_for_review()
        pa, entry = start_review_for_pa(pa_id=self.pa.id, actor=self.reviewer)
        self.assertEqual(pa.lifecycle_state, LifecycleState.IN_REVIEW)
        self.assertTrue(ReviewEntry.objects.filter(product_assignment=self.pa).exists())
        self.assertEqual(entry.assigned_reviewer, self.reviewer)
        self.assertIsNotNone(entry.review_started_at)

    def test_mark_filed_advances_lifecycle(self):
        self._advance_to_ready_for_review()
        start_review_for_pa(pa_id=self.pa.id, actor=self.reviewer)
        pa, entry = mark_filed_for_pa(
            pa_id=self.pa.id,
            actor=self.preparer,
            notes="Filed via Drake",
        )
        self.assertEqual(pa.lifecycle_state, LifecycleState.FILED)
        self.assertEqual(entry.filed_by, self.preparer)
        self.assertEqual(entry.notes, "Filed via Drake")
        self.assertIsNotNone(entry.filed_at)

    def test_queue_count_scoped_to_active_season(self):
        self._advance_to_ready_for_review()
        self.assertEqual(review_queue_count(), 1)

    def test_payment_status_for_cash(self):
        self._advance_to_ready_for_review()
        self.assertEqual(payment_status_label(self.pa), "Payment confirmed")

    def test_payment_status_for_paid_qbo_invoice(self):
        self.pa.payment_method = ProductAssignment.PAYMENT_METHOD_QBO
        self.pa.save(update_fields=["payment_method"])
        cmd_enter_clearing(pa_id=self.pa.id)
        cmd_complete_clearing(pa_id=self.pa.id)
        invoice = Invoice.objects.create(
            client=self.client_obj,
            status=Invoice.INVOICE_STATUS_PAID,
            qbo_invoice_number="1001",
        )
        AssignmentInvoiceLink.objects.create(product_assignment=self.pa, invoice=invoice)
        cmd_mark_ready_for_review(pa_id=self.pa.id)
        self.pa.refresh_from_db()
        self.assertEqual(payment_status_label(self.pa), "Paid")

    def test_review_page_requires_allowed_role(self):
        http = DjangoClient()
        http.login(email=self.denied_user.email, password="testpass123")
        resp = http.get(reverse("review:review"))
        self.assertEqual(resp.status_code, 403)

    def test_review_page_lists_ready_assignment(self):
        self._advance_to_ready_for_review()
        http = DjangoClient()
        http.login(email=self.reviewer.email, password="testpass123")
        resp = http.get(reverse("review:review"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Review Test Client")
        self.assertContains(resp, "Start review")

    def test_start_review_endpoint(self):
        self._advance_to_ready_for_review()
        http = DjangoClient()
        http.login(email=self.reviewer.email, password="testpass123")
        resp = http.post(reverse("review:start_review", args=[self.pa.id]))
        self.assertEqual(resp.status_code, 200)
        self.pa.refresh_from_db()
        self.assertEqual(self.pa.lifecycle_state, LifecycleState.IN_REVIEW)

    def test_mark_filed_endpoint(self):
        self._advance_to_ready_for_review()
        start_review_for_pa(pa_id=self.pa.id, actor=self.reviewer)
        http = DjangoClient()
        http.login(email=self.preparer.email, password="testpass123")
        resp = http.post(
            reverse("review:mark_filed", args=[self.pa.id]),
            data='{"notes": "Done"}',
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.pa.refresh_from_db()
        self.assertEqual(self.pa.lifecycle_state, LifecycleState.FILED)

    def test_queue_count_api(self):
        self._advance_to_ready_for_review()
        http = DjangoClient()
        http.login(email=self.reviewer.email, password="testpass123")
        resp = http.get(reverse("review:queue_count"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 1)

    def test_cannot_mark_filed_from_ready_for_review(self):
        self._advance_to_ready_for_review()
        http = DjangoClient()
        http.login(email=self.reviewer.email, password="testpass123")
        resp = http.post(
            reverse("review:mark_filed", args=[self.pa.id]),
            data="{}",
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
