import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_health(client):
    url = reverse("health")
    resp = client.get(url)
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
