import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from core.models import Client, Intake, Organization, ProductAssignment, TaxSeason
from core.services.mvp_demo import (
    DEMO_CLIENT_TIN,
    DEMO_ORG_NAME,
    DEMO_USER_EMAILS,
    mvp_demo_readiness_issues,
    seed_mvp_demo,
)

User = get_user_model()


class MvpDemoSeedTests(TestCase):
    def test_seed_creates_org_tax_season_and_users(self):
        result = seed_mvp_demo(password="demo-pass")

        self.assertEqual(result.organization.name, DEMO_ORG_NAME)
        self.assertEqual(result.tax_season.year, timezone.now().year)
        self.assertTrue(result.tax_season.is_active)
        self.assertEqual(result.users_created, 4)
        self.assertEqual(User.objects.filter(email__in=DEMO_USER_EMAILS).count(), 4)

        dev = User.objects.get(email="developer@demo.pdk.local")
        self.assertTrue(dev.is_superuser)
        self.assertTrue(dev.check_password("demo-pass"))

    def test_seed_is_idempotent(self):
        seed_mvp_demo(password="first-pass")
        result = seed_mvp_demo(password="second-pass")

        self.assertEqual(result.users_created, 0)
        self.assertEqual(Organization.objects.filter(name=DEMO_ORG_NAME).count(), 1)
        self.assertEqual(TaxSeason.objects.filter(year=timezone.now().year).count(), 1)
        self.assertTrue(User.objects.get(email="preparer@demo.pdk.local").check_password("first-pass"))

    def test_reset_passwords(self):
        seed_mvp_demo(password="old-pass")
        seed_mvp_demo(password="new-pass", reset_passwords=True)
        self.assertTrue(User.objects.get(email="preparer@demo.pdk.local").check_password("new-pass"))

    def test_with_sample_client_enrolls_intake(self):
        result = seed_mvp_demo(password="demo-pass", with_sample_client=True)

        self.assertIsNotNone(result.sample_client)
        client = Client.objects.get(TIN=DEMO_CLIENT_TIN)
        season = TaxSeason.objects.get(year=timezone.now().year, is_active=True)
        intake = Intake.objects.get(client=client, tax_season=season)
        self.assertTrue(intake.is_active)
        self.assertTrue(ProductAssignment.objects.filter(intake=intake, is_active=True).exists())

    def test_readiness_passes_after_seed(self):
        seed_mvp_demo(password="demo-pass")
        self.assertEqual(mvp_demo_readiness_issues(), [])

    def test_readiness_fails_without_seed(self):
        TaxSeason.objects.create(
            year=timezone.now().year - 1,
            start_date=datetime.date(2024, 1, 1),
            end_date=datetime.date(2024, 10, 15),
            is_active=True,
        )
        issues = mvp_demo_readiness_issues()
        self.assertTrue(any("organization" in i.lower() or "demo users" in i.lower() for i in issues))
