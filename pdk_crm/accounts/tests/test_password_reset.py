from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

import pyotp

from accounts.models import AuthenticatorDevice, PasswordResetChallenge
import re
from accounts.validators import SpecialCharacterValidator, password_strength_label

User = get_user_model()


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    PASSWORD_RESET_NOTIFY_EMAILS=["owner-notify@example.com", "dev-notify@example.com"],
)
class PasswordResetFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from core.models import Organization

        cls.org = Organization.objects.create(name="Reset Test Org")
        cls.user = User.objects.create_user(
            email="preparer@reset.test",
            password="OldPass1!",
            organization=cls.org,
            role="tax_preparer",
            first_name="Pat",
            last_name="Preparer",
        )
        cls.device = AuthenticatorDevice.objects.create(
            user=cls.user,
            secret=pyotp.random_base32(),
            confirmed_at=timezone.now(),
        )

    def test_login_page_has_reset_links(self):
        response = self.client.get(reverse("accounts:login"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("accounts:password_reset"))
        self.assertContains(response, reverse("accounts:authenticator_setup"))

    def test_password_reset_happy_path(self):
        response = self.client.post(
            reverse("accounts:password_reset"),
            {"email": self.user.email},
        )
        self.assertEqual(response.status_code, 302)
        challenge = PasswordResetChallenge.objects.get(user=self.user)
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(mail.outbox[0].to, [self.user.email])
        self.assertEqual(mail.outbox[1].to, ["owner-notify@example.com", "dev-notify@example.com"])

        match = re.search(r"verification code is: (\d{6})", mail.outbox[0].body)
        self.assertIsNotNone(match)
        email_code = match.group(1)

        response = self.client.post(
            reverse("accounts:password_reset_verify_email", kwargs={"challenge_id": challenge.id}),
            {"code": email_code},
        )
        self.assertEqual(response.status_code, 302)

        totp = pyotp.TOTP(self.device.secret)
        response = self.client.post(
            reverse("accounts:password_reset_verify_totp", kwargs={"challenge_id": challenge.id}),
            {"code": totp.now()},
        )
        self.assertEqual(response.status_code, 302)

        response = self.client.post(
            reverse("accounts:password_reset_confirm", kwargs={"challenge_id": challenge.id}),
            {"new_password1": "NewSecure1!", "new_password2": "NewSecure1!"},
        )
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("NewSecure1!"))

    def test_reset_enrolls_authenticator_when_missing(self):
        self.device.delete()

        response = self.client.post(
            reverse("accounts:password_reset"),
            {"email": self.user.email},
        )
        self.assertEqual(response.status_code, 302)
        challenge = PasswordResetChallenge.objects.get(user=self.user)

        match = re.search(r"verification code is: (\d{6})", mail.outbox[0].body)
        email_code = match.group(1)
        response = self.client.post(
            reverse("accounts:password_reset_verify_email", kwargs={"challenge_id": challenge.id}),
            {"code": email_code},
        )
        self.assertRedirects(
            response,
            reverse("accounts:password_reset_enroll_authenticator", kwargs={"challenge_id": challenge.id}),
        )

        response = self.client.get(
            reverse("accounts:password_reset_enroll_authenticator", kwargs={"challenge_id": challenge.id}),
        )
        self.assertEqual(response.status_code, 200)

        device = AuthenticatorDevice.objects.get(user=self.user)
        totp = pyotp.TOTP(device.secret)
        response = self.client.post(
            reverse("accounts:password_reset_enroll_authenticator", kwargs={"challenge_id": challenge.id}),
            {"code": totp.now()},
        )
        self.assertRedirects(
            response,
            reverse("accounts:password_reset_confirm", kwargs={"challenge_id": challenge.id}),
        )

        response = self.client.post(
            reverse("accounts:password_reset_confirm", kwargs={"challenge_id": challenge.id}),
            {"new_password1": "FreshPass1!", "new_password2": "FreshPass1!"},
        )
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("FreshPass1!"))
        device.refresh_from_db()
        self.assertIsNotNone(device.confirmed_at)

    def test_unknown_email_does_not_create_challenge(self):
        response = self.client.post(
            reverse("accounts:password_reset"),
            {"email": "missing@reset.test"},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(PasswordResetChallenge.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 0)


class AuthenticatorSetupTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from core.models import Organization

        cls.org = Organization.objects.create(name="TOTP Test Org")
        cls.user = User.objects.create_user(
            email="reviewer@totp.test",
            password="Current1!",
            organization=cls.org,
            role="reviewer",
        )

    def test_authenticator_setup_enrolls_device(self):
        response = self.client.post(
            reverse("accounts:authenticator_setup"),
            {"email": self.user.email, "password": "Current1!"},
        )
        self.assertEqual(response.status_code, 302)

        device = AuthenticatorDevice.objects.get(user=self.user)
        totp = pyotp.TOTP(device.secret)
        response = self.client.post(
            reverse("accounts:authenticator_setup_confirm"),
            {"code": totp.now()},
        )
        self.assertEqual(response.status_code, 302)
        device.refresh_from_db()
        self.assertIsNotNone(device.confirmed_at)


class PasswordPolicyTests(TestCase):
    def test_special_character_validator(self):
        validator = SpecialCharacterValidator()
        with self.assertRaises(Exception):
            validator.validate("abcdefgh")

    def test_password_strength_labels(self):
        self.assertEqual(password_strength_label(""), "weak")
        self.assertEqual(password_strength_label("short"), "weak")
        self.assertEqual(password_strength_label("Long-enough1!"), "very_strong")
