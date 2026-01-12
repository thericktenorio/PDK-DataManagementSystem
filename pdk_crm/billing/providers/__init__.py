from django.conf import settings
from .qbo_provider import QboProvider
from .fake_provider import FakeProvider


def get_provider():
    key = getattr(settings, "BILLING_PROVIDER", "fake").strip().lower()
    if key == "qbo":
        return QboProvider()
    return FakeProvider()
