from django.test import TestCase
from django.urls import reverse


class HealthTests(TestCase):
    def test_health_returns_ok(self):
        response = self.client.get(reverse("health"))
        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(response.content, {"status": "ok"})
