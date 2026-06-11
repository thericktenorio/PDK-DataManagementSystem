import json

from django.contrib.auth import get_user_model
from django.test import Client as HttpClient, TestCase
from django.urls import reverse

from core.models import Client, Organization

User = get_user_model()


class ClientPortfolioDeleteTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Test Org")
        self.user = User.objects.create_user(
            email="portfolio-test@example.com",
            password="testpass123",
            organization=self.org,
            role="developer",
        )
        self.http = HttpClient()
        self.http.force_login(self.user)
        self.client_row = Client.objects.create(TIN="111223333", name="Delete Me")

    def test_delete_client_removes_row(self):
        url = reverse("client_portfolio:delete_client", args=[self.client_row.id])
        response = self.http.delete(url)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data["status"], "success")
        self.assertFalse(Client.objects.filter(pk=self.client_row.id).exists())
