import uuid
from datetime import date

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings

from core.models import Organization
from core.backgrounds import (
    BACKGROUNDS,
    FIXED_BACKGROUND_KEY,
    SESSION_BACKGROUND_KEY,
    SESSION_DATE_KEY,
    select_background_key,
    sync_session_background,
)
from core.middleware import AppBackgroundMiddleware


class AppBackgroundSelectionTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name=f"Org {uuid.uuid4().hex[:8]}")

    def test_select_background_key_is_stable_for_user_and_day(self):
        key_a = select_background_key(7, date(2026, 6, 9))
        key_b = select_background_key(7, date(2026, 6, 9))
        key_c = select_background_key(7, date(2026, 6, 10))

        self.assertEqual(key_a, key_b)
        self.assertIn(key_a, {entry.key for entry in BACKGROUNDS})
        self.assertIn(key_c, {entry.key for entry in BACKGROUNDS})

    def test_sync_session_background_reuses_same_day_selection(self):
        user = get_user_model().objects.create_user(
            email="bg-user@example.com",
            password="test-pass-123",
            organization=self.org,
            rotate_background=True,
        )
        request = RequestFactory().get("/")
        request.user = user
        request.session = self.client.session

        first = sync_session_background(request)
        second = sync_session_background(request)

        self.assertEqual(first, second)
        from core.backgrounds import firm_localdate

        self.assertEqual(request.session[SESSION_DATE_KEY], firm_localdate().isoformat())
        self.assertEqual(request.session[SESSION_BACKGROUND_KEY], first)

    @override_settings(TIME_ZONE="America/Los_Angeles")
    def test_sync_session_background_refreshes_on_new_calendar_day(self):
        user = get_user_model().objects.create_user(
            email="bg-user-2@example.com",
            password="test-pass-123",
            organization=self.org,
            rotate_background=True,
        )
        request = RequestFactory().get("/")
        request.user = user
        request.session = self.client.session
        request.session[SESSION_DATE_KEY] = "2020-01-01"
        request.session[SESSION_BACKGROUND_KEY] = BACKGROUNDS[0].key

        refreshed = sync_session_background(request)

        from core.backgrounds import firm_localdate

        self.assertEqual(request.session[SESSION_DATE_KEY], firm_localdate().isoformat())
        self.assertIn(refreshed, {entry.key for entry in BACKGROUNDS})

    def test_rotation_disabled_uses_fixed_background(self):
        user = get_user_model().objects.create_user(
            email="bg-user-fixed@example.com",
            password="test-pass-123",
            organization=self.org,
            rotate_background=False,
        )
        request = RequestFactory().get("/")
        request.user = user
        request.session = self.client.session

        self.assertEqual(sync_session_background(request), FIXED_BACKGROUND_KEY)

    def test_middleware_sets_session_for_authenticated_user(self):
        user = get_user_model().objects.create_user(
            email="bg-user-3@example.com",
            password="test-pass-123",
            organization=self.org,
            rotate_background=True,
        )
        self.client.force_login(user)
        session = self.client.session
        session.pop(SESSION_DATE_KEY, None)
        session.pop(SESSION_BACKGROUND_KEY, None)
        session.save()

        def get_response(request):
            from django.http import HttpResponse

            return HttpResponse("ok")

        request = RequestFactory().get("/intake/")
        request.user = user
        request.session = self.client.session
        AppBackgroundMiddleware(get_response)(request)

        from core.backgrounds import firm_localdate

        self.assertEqual(request.session[SESSION_DATE_KEY], firm_localdate().isoformat())
        self.assertIn(request.session[SESSION_BACKGROUND_KEY], {entry.key for entry in BACKGROUNDS})
