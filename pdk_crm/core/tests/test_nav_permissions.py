from django.test import TestCase

from accounts.models import InternalUser
from core.models import Organization
from core.nav_permissions import (
    ALL_NAV_KEYS,
    nav_apps_for_user,
    nav_keys_for_role,
    user_can_access_nav_view,
)


class NavPermissionsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Nav Test Org")

    def _user(self, role: str, email: str) -> InternalUser:
        return InternalUser.objects.create_user(
            email=email,
            password="test-pass-123",
            organization=self.org,
            role=role,
            first_name="Demo",
            last_name=role,
        )

    def test_manager_has_all_nav_keys(self):
        self.assertEqual(nav_keys_for_role("manager"), ALL_NAV_KEYS)

    def test_office_admin_nav_keys(self):
        keys = nav_keys_for_role("office_admin")
        self.assertEqual(keys, frozenset({"home", "calendar", "intake", "client_portfolio"}))

    def test_reviewer_includes_review_not_client_portfolio(self):
        keys = nav_keys_for_role("reviewer")
        self.assertIn("review", keys)
        self.assertIn("billing", keys)
        self.assertNotIn("client_portfolio", keys)
        self.assertNotIn("analytics", keys)

    def test_tax_preparer_cannot_access_billing_page(self):
        user = self._user("tax_preparer", "preparer@nav.test")
        self.assertFalse(user_can_access_nav_view(user, "billing:billing"))
        self.assertTrue(user_can_access_nav_view(user, "clearing:clearing"))

    def test_nav_apps_for_user_filters_dock_entries(self):
        user = self._user("billing", "billing@nav.test")
        urls = {app["url"] for app in nav_apps_for_user(user)}
        self.assertEqual(
            urls,
            {"core:home", "pdk_calendar:pdk_calendar", "billing:billing"},
        )
