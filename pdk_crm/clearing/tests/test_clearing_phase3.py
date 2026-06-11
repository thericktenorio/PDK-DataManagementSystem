import datetime
import json
from decimal import Decimal
import uuid

from django.contrib.auth import get_user_model
from django.test import Client as HttpClient, TestCase
from django.urls import reverse
from django.core.exceptions import ValidationError

from core.models import (
    Client,
    DailyClearing,
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
    cmd_enter_clearing,
    cmd_reopen_clearing,
    validate_pa_ready_for_clearing,
)

User = get_user_model()


class ClearingPhase3Tests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name=f"Org {uuid.uuid4().hex[:8]}")
        self.user = User.objects.create_user(
            email=f"preparer-{uuid.uuid4().hex[:8]}@example.com",
            password="testpass123",
            organization=self.org,
            role="tax_preparer",
        )
        self.http = HttpClient()
        self.http.force_login(self.user)

        self.client_obj = Client.objects.create(TIN="987654321", name="Clearing Client")
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
        self.filing_type = FilingType.objects.filter(
            filing_type=FilingType.FILING_TYPE_DEFAULT
        ).order_by("id").first()
        if self.filing_type is None:
            self.filing_type = FilingType.objects.create(
                filing_type=FilingType.FILING_TYPE_DEFAULT
            )
        self.product = Product.objects.create(
            tax_year=self.tax_year,
            product_type=Product.PRODUCT_TYPE_DEFAULT,
            is_product_active=False,
            default_price="150.00",
        )
        self.pa, _ = ProductAssignment.objects.create_product_assignment(
            client=self.client_obj,
            intake=self.intake,
            tax_year=self.tax_year,
            product=self.product,
            filing_type=self.filing_type,
            is_active=True,
        )
        cmd_enter_clearing(pa_id=self.pa.id, actor=self.user)
        DailyClearing.objects.create(
            client=self.client_obj,
            tax_season=self.tax_season,
            is_active=True,
        )

    def _make_pa_ready(self):
        self.pa.refresh_from_db()
        self.pa.payment_method = ProductAssignment.PAYMENT_METHOD_CASH
        self.pa.preparer = self.user
        self.pa.closing_message_text = "Your return is ready."
        self.pa.fee = Decimal(str(self.product.default_price))
        self.pa.save(
            update_fields=[
                "payment_method",
                "preparer",
                "closing_message_text",
                "fee",
            ]
        )

    def test_fee_default_on_pa_creation(self):
        self.assertEqual(self.pa.fee, Decimal(str(self.product.default_price)))

    def test_validate_requires_message_and_preparer(self):
        self.pa.payment_method = ProductAssignment.PAYMENT_METHOD_CASH
        self.pa.fee = Decimal(str(self.product.default_price))
        self.pa.save(update_fields=["payment_method", "fee"])
        with self.assertRaises(ValidationError) as ctx:
            validate_pa_ready_for_clearing(self.pa)
        self.assertIn("preparer", ctx.exception.message_dict)
        self.assertIn("closing_message_text", ctx.exception.message_dict)

    def test_validate_rejects_zero_fee_for_paid_methods(self):
        self._make_pa_ready()
        self.pa.fee = Decimal("0")
        self.pa.save(update_fields=["fee"])
        with self.assertRaises(ValidationError) as ctx:
            validate_pa_ready_for_clearing(self.pa)
        self.assertIn("fee", ctx.exception.message_dict)

    def test_complete_clearing_endpoint(self):
        self._make_pa_ready()
        url = reverse("clearing:complete_clearing", kwargs={"pa_id": self.pa.id})
        resp = self.http.post(url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["lifecycle_state"], LifecycleState.CLEARING_COMPLETE)
        self.assertTrue(data["is_locked"])

    def test_complete_clearing_validation_failure(self):
        url = reverse("clearing:complete_clearing", kwargs={"pa_id": self.pa.id})
        resp = self.http.post(url)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["code"], "VALIDATION")

    def test_reopen_clearing_requires_fee(self):
        self._make_pa_ready()
        cmd_complete_clearing(pa_id=self.pa.id, actor=self.user)
        url = reverse("clearing:reopen_clearing", kwargs={"pa_id": self.pa.id})
        resp = self.http.post(url, data=json.dumps({}), content_type="application/json")
        self.assertEqual(resp.status_code, 400)

    def test_reopen_clearing_success(self):
        self._make_pa_ready()
        cmd_complete_clearing(pa_id=self.pa.id, actor=self.user)
        url = reverse("clearing:reopen_clearing", kwargs={"pa_id": self.pa.id})
        resp = self.http.post(
            url,
            data=json.dumps({"confirmed_fee": "175.00"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.pa.refresh_from_db()
        self.assertEqual(self.pa.lifecycle_state, LifecycleState.IN_CLEARING)
        self.assertEqual(str(self.pa.fee), "175.00")

    def test_client_message_get_and_post(self):
        url = reverse("clearing:client_message", kwargs={"pa_id": self.pa.id})
        get_resp = self.http.get(url)
        self.assertEqual(get_resp.status_code, 200)

        post_resp = self.http.post(
            url,
            data=json.dumps({"message_text": "Hello client"}),
            content_type="application/json",
        )
        self.assertEqual(post_resp.status_code, 200)
        self.pa.refresh_from_db()
        self.assertEqual(self.pa.closing_message_text, "Hello client")

    def test_cmd_reopen_clearing_idempotent(self):
        self._make_pa_ready()
        cmd_complete_clearing(pa_id=self.pa.id, actor=self.user)
        pa = cmd_reopen_clearing(
            pa_id=self.pa.id,
            actor=self.user,
            confirmed_fee="150.00",
        )
        self.assertEqual(pa.lifecycle_state, LifecycleState.IN_CLEARING)
        pa = cmd_reopen_clearing(
            pa_id=self.pa.id,
            actor=self.user,
            confirmed_fee="150.00",
        )
        self.assertEqual(pa.lifecycle_state, LifecycleState.IN_CLEARING)

    def test_add_product_assignment_creates_second_entry(self):
        url = reverse("clearing:add_product_assignment")
        resp = self.http.post(
            url,
            data=json.dumps({"client_id": self.client_obj.id}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertEqual(data["status"], "success")
        new_pa_id = data["product_assignment"]["id"]
        self.assertNotEqual(new_pa_id, self.pa.id)

        active_count = ProductAssignment.objects.filter(
            client=self.client_obj,
            intake=self.intake,
            is_active=True,
        ).count()
        self.assertEqual(active_count, 2)

    def test_create_new_client_enrolls_intake_and_clearing(self):
        resp = self.http.post(
            reverse("clearing:create_new_client"),
            data=json.dumps(
                {
                    "TIN": "555555555",
                    "name": "Clearing New Client",
                    "email": "new@example.com",
                    "phone": "5555555555",
                    "filing_type": "Simple",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertEqual(data["status"], "success")

        client = Client.objects.get(pk=data["client_id"])
        intake = Intake.objects.get(client=client, tax_season=self.tax_season, is_active=True)
        self.assertTrue(
            DailyClearing.objects.filter(
                client=client, tax_season=self.tax_season, is_active=True
            ).exists()
        )
        self.assertTrue(
            ProductAssignment.objects.filter(client=client, intake=intake, is_active=True).exists()
        )

    def test_create_new_client_accepts_formatted_tin_and_phone(self):
        resp = self.http.post(
            reverse("clearing:create_new_client"),
            data=json.dumps(
                {
                    "TIN": "123-45-6789",
                    "name": "Formatted Input Client",
                    "email": "formatted@example.com",
                    "phone": "(555) 123-4567",
                    "filing_type": "Simple",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertEqual(data["status"], "success")

        client = Client.objects.get(pk=data["client_id"])
        self.assertEqual(client.TIN, "123456789")
        self.assertEqual(client.phone, "5551234567")
