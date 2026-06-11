"""Review Phase 7 tests — four-table workflow (W2)."""
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
    cmd_set_pending_reject_correction,
    cmd_start_ack_reconciling,
)
from review.models import ReviewEntry
from review.selectors import (
    payment_status_label,
    review_queue_count,
    review_table_queryset,
)
from review.services.queue import (
    complete_reject_correction_for_pa,
    complete_review_for_pa,
)

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

    def test_complete_review_from_ready_advances_to_filed(self):
        self._advance_to_ready_for_review()
        pa, entry = complete_review_for_pa(
            pa_id=self.pa.id,
            actor=self.reviewer,
            notes="Looks good",
            expected_ack_count=2,
        )
        self.assertEqual(pa.lifecycle_state, LifecycleState.FILED)
        self.assertEqual(pa.expected_ack_count, 2)
        self.assertEqual(entry.notes, "Looks good")
        self.assertIsNotNone(entry.filed_at)

    def test_four_table_querysets(self):
        self._advance_to_ready_for_review()
        self.assertEqual(review_table_queryset(table="ready").count(), 1)

        complete_review_for_pa(pa_id=self.pa.id, actor=self.reviewer, expected_ack_count=1)
        self.assertEqual(review_table_queryset(table="ready").count(), 0)
        self.assertEqual(review_table_queryset(table="pending_acks").count(), 1)

        cmd_start_ack_reconciling(pa_id=self.pa.id)
        cmd_set_pending_reject_correction(pa_id=self.pa.id)
        self.pa.refresh_from_db()
        self.assertEqual(review_table_queryset(table="pending_reject").count(), 1)

        complete_reject_correction_for_pa(pa_id=self.pa.id, actor=self.reviewer)
        self.pa.refresh_from_db()
        self.assertEqual(self.pa.lifecycle_state, LifecycleState.ACK_RECONCILING)
        self.assertEqual(review_table_queryset(table="pending_acks").count(), 1)

        self.pa.lifecycle_state = LifecycleState.CLOSED
        self.pa.save(update_fields=["lifecycle_state"])
        self.assertEqual(review_table_queryset(table="filed").count(), 1)

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
        self.assertContains(resp, "Review Complete")
        self.assertNotContains(resp, "Start review")

    def test_complete_review_endpoint(self):
        self._advance_to_ready_for_review()
        http = DjangoClient()
        http.login(email=self.reviewer.email, password="testpass123")
        resp = http.post(
            reverse("review:complete_review", args=[self.pa.id]),
            data='{"expected_ack_count": 1}',
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.pa.refresh_from_db()
        self.assertEqual(self.pa.lifecycle_state, LifecycleState.FILED)

    def test_complete_reject_correction_endpoint(self):
        self._advance_to_ready_for_review()
        complete_review_for_pa(pa_id=self.pa.id, actor=self.reviewer, expected_ack_count=1)
        cmd_start_ack_reconciling(pa_id=self.pa.id)
        cmd_set_pending_reject_correction(pa_id=self.pa.id)
        http = DjangoClient()
        http.login(email=self.reviewer.email, password="testpass123")
        resp = http.post(
            reverse("review:complete_reject_correction", args=[self.pa.id]),
            data="{}",
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.pa.refresh_from_db()
        self.assertEqual(self.pa.lifecycle_state, LifecycleState.ACK_RECONCILING)

    def test_queue_count_api(self):
        self._advance_to_ready_for_review()
        http = DjangoClient()
        http.login(email=self.reviewer.email, password="testpass123")
        resp = http.get(reverse("review:queue_count"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 1)

    def test_review_entry_created_on_complete_review(self):
        self._advance_to_ready_for_review()
        complete_review_for_pa(pa_id=self.pa.id, actor=self.reviewer)
        self.assertTrue(ReviewEntry.objects.filter(product_assignment=self.pa).exists())
