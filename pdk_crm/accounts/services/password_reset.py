from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.utils import timezone

from accounts.models import PasswordResetChallenge

User = get_user_model()

CHALLENGE_TTL_MINUTES = 30


def _hash_code(code: str) -> str:
    pepper = settings.SECRET_KEY or ""
    return hashlib.sha256(f"{pepper}:{code}".encode()).hexdigest()


def generate_email_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def notify_emails_for_password_reset() -> list[str]:
    configured = getattr(settings, "PASSWORD_RESET_NOTIFY_EMAILS", None) or []
    emails = [e.strip() for e in configured if e and e.strip()]
    if emails:
        return emails

    role_emails = (
        User.objects.filter(role__in=("developer", "owner"), is_active=True)
        .values_list("email", flat=True)
        .distinct()
    )
    return [email for email in role_emails if email]


def create_password_reset_challenge(*, user) -> tuple[PasswordResetChallenge, str]:
    email_code = generate_email_code()
    challenge = PasswordResetChallenge.objects.create(
        user=user,
        email_code_hash=_hash_code(email_code),
        expires_at=timezone.now() + timedelta(minutes=CHALLENGE_TTL_MINUTES),
    )
    return challenge, email_code


def verify_email_code(*, challenge: PasswordResetChallenge, code: str) -> bool:
    if challenge.is_expired or challenge.is_completed:
        return False
    normalized = (code or "").strip().replace(" ", "")
    if not normalized.isdigit() or len(normalized) != 6:
        return False
    if _hash_code(normalized) != challenge.email_code_hash:
        return False
    if challenge.email_verified_at is None:
        challenge.email_verified_at = timezone.now()
        challenge.save(update_fields=["email_verified_at"])
    return True


def mark_totp_verified(*, challenge: PasswordResetChallenge) -> None:
    if challenge.totp_verified_at is None:
        challenge.totp_verified_at = timezone.now()
        challenge.save(update_fields=["totp_verified_at"])


def complete_challenge(*, challenge: PasswordResetChallenge) -> None:
    challenge.completed_at = timezone.now()
    challenge.save(update_fields=["completed_at"])


def send_password_reset_email(*, user, email_code: str) -> None:
    subject = "PDK ENTRUST — password reset verification code"
    message = (
        f"A password reset was requested for {user.email}.\n\n"
        f"Your verification code is: {email_code}\n\n"
        "This code expires in 30 minutes. If you did not request a reset, "
        "contact your administrator."
    )
    send_mail(
        subject,
        message,
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
        fail_silently=False,
    )


def _display_name(user) -> str:
    full_name = f"{user.first_name} {user.last_name}".strip()
    return full_name or user.email


def send_password_reset_admin_notice(*, user) -> None:
    recipients = notify_emails_for_password_reset()
    if not recipients:
        return

    subject = "PDK ENTRUST — team member password reset requested"
    message = (
        f"{_display_name(user)} ({user.email}, role: {user.role}) "
        "requested a password reset.\n\n"
        "No action is required unless this looks suspicious."
    )
    send_mail(
        subject,
        message,
        settings.DEFAULT_FROM_EMAIL,
        recipients,
        fail_silently=False,
    )
