import pytest


@pytest.fixture(autouse=True)
def _sqlite_for_tests(settings):
    # Ensure any incidental DB usage goes to in-memory SQLite
    settings.DATABASES["default"] = {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
