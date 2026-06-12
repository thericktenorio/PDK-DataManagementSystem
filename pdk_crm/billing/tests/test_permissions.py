import json
import uuid

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from billing.permissions import user_can_manage_billing_settings
from core.models import Organization

User = get_user_model()


class BillingSettingsPermissionsTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name=f"Org {uuid.uuid4().hex[:8]}")
        self.manager = User.objects.create_user(
            email=f"mgr-{uuid.uuid4().hex[:8]}@example.com",
            password="testpass123",
            organization=self.org,
            role="manager",
        )
        self.billing_agent = User.objects.create_user(
            email=f"bill-{uuid.uuid4().hex[:8]}@example.com",
            password="testpass123",
            organization=self.org,
            role="billing",
        )

    def test_manage_billing_settings_roles(self):
        self.assertTrue(user_can_manage_billing_settings(self.manager))
        self.assertFalse(user_can_manage_billing_settings(self.billing_agent))

    def test_billing_page_shows_readonly_controls_for_billing_agent(self):
        client = Client()
        client.force_login(self.billing_agent)
        response = client.get(reverse("billing:billing"))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn('disabled aria-disabled="true">Connect QBO</button>', html)
        self.assertIn('id="autoSendToggle"', html)
        self.assertIn('disabled aria-disabled="true"', html)

    def test_toggle_auto_send_forbidden_for_billing_agent(self):
        client = Client()
        client.force_login(self.billing_agent)
        response = client.post(
            reverse("billing:toggle_auto_send"),
            data=json.dumps({"enabled": True}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_qbo_connect_forbidden_for_billing_agent(self):
        client = Client()
        client.force_login(self.billing_agent)
        response = client.get(reverse("billing:qbo_connect"))
        self.assertEqual(response.status_code, 403)

    def test_toggle_auto_send_allowed_for_manager(self):
        client = Client()
        client.force_login(self.manager)
        response = client.post(
            reverse("billing:toggle_auto_send"),
            data=json.dumps({"enabled": True}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.org.refresh_from_db()
        self.assertTrue(self.org.auto_send_invoices_enabled)
