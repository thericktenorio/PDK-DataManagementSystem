import os
import uuid
from decimal import Decimal

from django.test import Client as DjangoTestClient, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from analytics.models import DimTaxSeason, EtlRun, FactAssignment
from analytics.permissions import user_can_access_analytics
from analytics.selectors import build_season_snapshot
from accounts.models import InternalUser
from core.models import Organization


def _dual_analytics_enabled() -> bool:
    return os.getenv("DJANGO_TEST_DUAL_ANALYTICS", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


class AnalyticsPermissionsTests(TransactionTestCase):
    databases = {"default"}

    def setUp(self):
        org = Organization.objects.create(name=f"Org-{uuid.uuid4().hex[:6]}")
        self.manager = InternalUser.objects.create_user(
            email=f"mgr-{uuid.uuid4().hex[:8]}@example.com",
            password="test-pass-123",
            organization=org,
            role="manager",
        )
        self.preparer = InternalUser.objects.create_user(
            email=f"prep-{uuid.uuid4().hex[:8]}@example.com",
            password="test-pass-123",
            organization=org,
            role="tax_preparer",
        )

    def test_manager_has_access_preparer_does_not(self):
        self.assertTrue(user_can_access_analytics(self.manager))
        self.assertFalse(user_can_access_analytics(self.preparer))


class AnalyticsDashboardViewTests(TransactionTestCase):
    databases = {"default", "analytics"}

    def setUp(self):
        if not _dual_analytics_enabled():
            self.skipTest("Requires DJANGO_TEST_DUAL_ANALYTICS=1")

        org = Organization.objects.create(name=f"Org-{uuid.uuid4().hex[:6]}")
        self.user = InternalUser.objects.create_user(
            email=f"own-{uuid.uuid4().hex[:8]}@example.com",
            password="test-pass-123",
            organization=org,
            role="owner",
        )
        DimTaxSeason.objects.using("analytics").create(
            source_tax_season_id=1,
            year=2099,
            is_active=True,
        )
        EtlRun.objects.using("analytics").create(
            status=EtlRun.Status.SUCCESS,
            finished_at=timezone.now(),
        )
        FactAssignment.objects.using("analytics").create(
            source_pa_id=1,
            source_client_id=10,
            tax_season_year=2099,
            lifecycle_state="CLOSED",
            expected_fee=Decimal("100.00"),
            actual_revenue_recognized=Decimal("100.00"),
            revenue_gap=Decimal("0.00"),
        )
        self.http = DjangoTestClient()

    def test_owner_can_load_dashboard(self):
        self.http.force_login(self.user)
        resp = self.http.get(reverse("analytics:analytics"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Analytics")
        self.assertContains(resp, "Services Pending")
        self.assertContains(resp, "Services Closed")
        self.assertContains(resp, "Tax PDFs Parsed")
        self.assertContains(resp, "analytics-kpi-card")
        self.assertContains(resp, "Expected (fees at clearing)")

    def test_preparer_forbidden(self):
        preparer = InternalUser.objects.create_user(
            email=f"p-{uuid.uuid4().hex[:8]}@example.com",
            password="test-pass-123",
            organization=self.user.organization,
            role="tax_preparer",
        )
        self.http.force_login(preparer)
        resp = self.http.get(reverse("analytics:analytics"))
        self.assertEqual(resp.status_code, 403)


class AnalyticsSelectorTests(TransactionTestCase):
    databases = {"default", "analytics"}

    def setUp(self):
        if not _dual_analytics_enabled():
            self.skipTest("Requires DJANGO_TEST_DUAL_ANALYTICS=1")

    def test_build_season_snapshot_aggregates(self):
        FactAssignment.objects.using("analytics").create(
            source_pa_id=101,
            source_client_id=1,
            tax_season_year=2025,
            lifecycle_state="IN_CLEARING",
            is_active=True,
            expected_fee=Decimal("200.00"),
            actual_revenue_recognized=Decimal("50.00"),
            revenue_gap=Decimal("150.00"),
            days_to_payment=10,
        )
        FactAssignment.objects.using("analytics").create(
            source_pa_id=102,
            source_client_id=2,
            tax_season_year=2025,
            lifecycle_state="CLOSED",
            is_active=True,
            expected_fee=Decimal("100.00"),
            actual_revenue_recognized=Decimal("100.00"),
            revenue_gap=Decimal("0.00"),
            days_to_payment=2,
        )
        FactAssignment.objects.using("analytics").create(
            source_pa_id=103,
            source_client_id=3,
            tax_season_year=2025,
            lifecycle_state="CANCELLED",
            is_active=False,
            expected_fee=Decimal("75.00"),
        )
        snap = build_season_snapshot(2025)
        self.assertEqual(snap.total_assignments, 1)
        self.assertEqual(snap.clients_serviced, 2)
        self.assertEqual(snap.expected_revenue, Decimal("300.00"))
        self.assertEqual(snap.recognized_revenue, Decimal("150.00"))
        self.assertEqual(snap.closed_count, 1)
        self.assertEqual(snap.cancelled_count, 1)
        self.assertEqual(snap.median_days_to_payment, 6)
