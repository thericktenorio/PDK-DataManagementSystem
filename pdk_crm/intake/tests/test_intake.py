import datetime
import json
import uuid

from django.contrib.auth import get_user_model
from django.test import Client as HttpClient, TestCase
from django.urls import reverse

from core.models import (
    Client,
    DailyClearing,
    FilingType,
    Intake,
    Organization,
    Product,
    ProductAssignment,
    TaxSeason,
    TaxYear,
)
from core.utils import INTAKE_PRODUCT_ASSIGNMENT_ORDERING
from intake.services.enrollment import enroll_client_in_intake, NoActiveTaxSeasonError

User = get_user_model()


class IntakeEnrollmentServiceTests(TestCase):
    def setUp(self):
        self.tax_season = TaxSeason.objects.create(
            year=2025,
            start_date=datetime.date(2025, 1, 1),
            end_date=datetime.date(2025, 10, 15),
            is_active=True,
        )
        self.client_obj = Client.objects.create(TIN="111111111", name="Enrollment Client")

    def test_enroll_creates_intake_and_product_assignment(self):
        payload = enroll_client_in_intake(self.client_obj)

        intake = Intake.objects.get(client=self.client_obj, tax_season=self.tax_season)
        self.assertTrue(intake.is_active)

        pa = ProductAssignment.objects.get(intake=intake, is_active=True)
        self.assertEqual(pa.client, self.client_obj)
        self.assertEqual(payload["product_assignment"]["id"], pa.id)
        self.assertFalse(DailyClearing.objects.filter(client=self.client_obj).exists())

    def test_enroll_reactivates_existing_intake(self):
        intake = Intake.objects.create(
            client=self.client_obj,
            tax_season=self.tax_season,
            is_active=False,
        )
        payload = enroll_client_in_intake(self.client_obj)

        intake.refresh_from_db()
        self.assertTrue(intake.is_active)
        self.assertEqual(
            ProductAssignment.objects.filter(intake=intake, is_active=True).count(),
            1,
        )
        self.assertIn("product_assignment", payload)

    def test_enroll_requires_active_tax_season(self):
        self.tax_season.is_active = False
        self.tax_season.save()

        with self.assertRaises(NoActiveTaxSeasonError):
            enroll_client_in_intake(self.client_obj)


class IntakeViewTests(TestCase):
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

        self.active_season = TaxSeason.objects.create(
            year=2025,
            start_date=datetime.date(2025, 1, 1),
            end_date=datetime.date(2025, 10, 15),
            is_active=True,
        )
        self.old_season = TaxSeason.objects.create(
            year=2024,
            start_date=datetime.date(2024, 1, 1),
            end_date=datetime.date(2024, 10, 15),
            is_active=False,
        )
        self.client_a = Client.objects.create(TIN="222222222", name="Active Season Client")
        self.client_b = Client.objects.create(TIN="333333333", name="Old Season Client")

        self.intake_a = Intake.objects.create(
            client=self.client_a,
            tax_season=self.active_season,
            is_active=True,
        )
        Intake.objects.create(
            client=self.client_b,
            tax_season=self.old_season,
            is_active=True,
        )

    def test_intake_page_shows_only_active_tax_season(self):
        response = self.http.get(reverse("intake:intake"))
        self.assertEqual(response.status_code, 200)
        names = [c.name for c in response.context["intake_clients"]]
        self.assertIn("Active Season Client", names)
        self.assertNotIn("Old Season Client", names)

    def test_create_new_client_auto_enrolls_in_intake(self):
        response = self.http.post(
            reverse("intake:create_new_client"),
            data=json.dumps({"TIN": "444444444", "name": "Brand New Client"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertIn("product_assignment", data)

        client = Client.objects.get(TIN="444444444")
        intake = Intake.objects.get(client=client, tax_season=self.active_season)
        self.assertTrue(intake.is_active)
        self.assertTrue(
            ProductAssignment.objects.filter(intake=intake, is_active=True).exists()
        )

    def test_portfolio_create_does_not_enroll_in_intake(self):
        response = self.http.post(
            reverse("client_portfolio:save_client"),
            data=json.dumps({"TIN": "555555555", "name": "Portfolio Client"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)

        client = Client.objects.get(TIN="555555555")
        self.assertFalse(Intake.objects.filter(client=client).exists())

    def test_remove_client_from_intake_accepts_post(self):
        tax_year = TaxYear.objects.create(client=self.client_a, year=2024)
        product = Product.objects.create(
            tax_year=tax_year,
            product_type=Product.PRODUCT_TYPE_DEFAULT,
            is_product_active=False,
        )
        intake = Intake.objects.get(client=self.client_a, tax_season=self.active_season)
        ProductAssignment.objects.create(
            client=self.client_a,
            intake=intake,
            tax_year=tax_year,
            product=product,
            is_active=True,
        )

        response = self.http.post(
            reverse("intake:remove_client_from_intake", args=[self.client_a.id])
        )
        self.assertEqual(response.status_code, 200)
        intake.refresh_from_db()
        self.assertFalse(intake.is_active)

    def test_remove_client_after_add_to_intake(self):
        client = Client.objects.create(TIN="666666666", name="Search Add Client")
        add_response = self.http.post(
            reverse("intake:add_client_to_intake", args=[client.id])
        )
        self.assertEqual(add_response.status_code, 200)
        self.assertEqual(add_response.json()["status"], "success")

        intake = Intake.objects.get(client=client, tax_season=self.active_season)
        self.assertTrue(intake.is_active)

        remove_response = self.http.post(
            reverse("intake:remove_client_from_intake", args=[client.id])
        )
        self.assertEqual(remove_response.status_code, 200)
        self.assertEqual(remove_response.json()["status"], "success")

        intake.refresh_from_db()
        self.assertFalse(intake.is_active)
        self.assertFalse(
            ProductAssignment.objects.filter(intake=intake, is_active=True).exists()
        )

    def test_remove_client_from_intake_without_active_product_assignments(self):
        intake = Intake.objects.get(client=self.client_a, tax_season=self.active_season)

        response = self.http.post(
            reverse("intake:remove_client_from_intake", args=[self.client_a.id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "success")

        intake.refresh_from_db()
        self.assertFalse(intake.is_active)

    def test_remove_client_after_re_add_clears_cancelled_lifecycle(self):
        client = Client.objects.create(TIN="777777777", name="Re-add Client")

        self.http.post(reverse("intake:add_client_to_intake", args=[client.id]))
        intake = Intake.objects.get(client=client, tax_season=self.active_season)
        pa = ProductAssignment.objects.get(intake=intake, is_active=True)
        self.assertIsNone(pa.lifecycle_state)

        self.http.post(reverse("intake:remove_client_from_intake", args=[client.id]))
        pa.refresh_from_db()
        self.assertFalse(pa.is_active)
        self.assertEqual(pa.lifecycle_state, "CANCELLED")

        self.http.post(reverse("intake:add_client_to_intake", args=[client.id]))
        pa.refresh_from_db()
        intake.refresh_from_db()
        self.assertTrue(intake.is_active)
        self.assertTrue(pa.is_active)
        self.assertIsNone(pa.lifecycle_state)

        remove_response = self.http.post(
            reverse("intake:remove_client_from_intake", args=[client.id])
        )
        self.assertEqual(remove_response.status_code, 200)
        self.assertEqual(remove_response.json()["status"], "success")

    def test_remove_client_heals_active_cancelled_product_assignment(self):
        from core.models import LifecycleState

        client = Client.objects.create(TIN="888888888", name="Stuck PA Client")
        intake = Intake.objects.create(
            client=client,
            tax_season=self.active_season,
            is_active=True,
        )
        tax_year = TaxYear.objects.create(client=client, year=2024)
        product = Product.objects.create(
            tax_year=tax_year,
            product_type=Product.PRODUCT_TYPE_DEFAULT,
            is_product_active=False,
        )
        pa = ProductAssignment.objects.create(
            client=client,
            intake=intake,
            tax_year=tax_year,
            product=product,
            is_active=True,
            lifecycle_state=LifecycleState.CANCELLED,
            cancellation_reason="Prior removal",
        )

        response = self.http.post(
            reverse("intake:remove_client_from_intake", args=[client.id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "success")

        pa.refresh_from_db()
        intake.refresh_from_db()
        self.assertFalse(pa.is_active)
        self.assertFalse(intake.is_active)

    def test_intake_page_orders_product_assignments(self):
        filing_joint, _ = FilingType.objects.get_or_create(filing_type="Joint")
        filing_single, _ = FilingType.objects.get_or_create(filing_type="Single")

        def make_pa(year, product_type, filing_type):
            tax_year = TaxYear.objects.create(client=self.client_a, year=year)
            product = Product.objects.create(
                tax_year=tax_year,
                product_type=product_type,
                is_product_active=False,
            )
            return ProductAssignment.objects.create(
                client=self.client_a,
                intake=self.intake_a,
                tax_year=tax_year,
                product=product,
                filing_type=filing_type,
                is_active=True,
            )

        make_pa(2023, Product.PRODUCT_TYPE_DEFAULT, filing_single)
        make_pa(2025, "Advisory", filing_joint)
        make_pa(2024, "Bookkeeping", filing_single)

        response = self.http.get(reverse("intake:intake"))
        client_ctx = next(c for c in response.context["intake_clients"] if c.id == self.client_a.id)
        ordered_ids = list(
            client_ctx.product_assignments_list.order_by(*INTAKE_PRODUCT_ASSIGNMENT_ORDERING).values_list(
                "id", flat=True
            )
        )
        rendered_ids = [pa.id for pa in client_ctx.product_assignments_list]
        self.assertEqual(rendered_ids, ordered_ids)
        self.assertEqual(
            [pa.tax_year.year for pa in client_ctx.product_assignments_list],
            [2025, 2024, 2023],
        )

    def test_add_product_assignment_rejects_duplicate_tax_year_product(self):
        tax_year = TaxYear.objects.create(client=self.client_a, year=2024)
        product = Product.objects.create(
            tax_year=tax_year,
            product_type=Product.PRODUCT_TYPE_DEFAULT,
            is_product_active=False,
        )
        ProductAssignment.objects.create(
            client=self.client_a,
            intake=self.intake_a,
            tax_year=tax_year,
            product=product,
            is_active=True,
        )

        response = self.http.post(
            reverse("intake:add_product_assignment"),
            data=json.dumps({"client_id": self.client_a.id}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "DUPLICATE_PA")

    def test_search_marks_in_intake_for_active_season_only(self):
        response = self.http.get(
            reverse("intake:search_clients"),
            {"q": "222222222"},
        )
        self.assertEqual(response.status_code, 200)
        result = response.json()[0]
        self.assertTrue(result["in_intake"])

        response = self.http.get(
            reverse("intake:search_clients"),
            {"q": "333333333"},
        )
        result = response.json()[0]
        self.assertFalse(result["in_intake"])
