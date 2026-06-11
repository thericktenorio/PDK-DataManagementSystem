"""Shareholder QA demo users — one login per role at @pdkentrust.com (dev/beta only)."""
from __future__ import annotations

from dataclasses import dataclass

from django.contrib.auth import get_user_model

from core.models import Organization
from core.services.mvp_demo import DEMO_ORG_NAME

User = get_user_model()

SUPERUSER_EMAIL = "thericktenorio@gmail.com"
SUPERUSER_FIRST_NAME = "Rick"
SUPERUSER_LAST_NAME = "Tenorio"

# Roles seeded for QA walkthroughs (developer/superuser excluded — use SUPERUSER_EMAIL).
ROLE_DEMO_SPECS: tuple[tuple[str, str], ...] = (
    ("office_admin", "Office Admin"),
    ("data_entry_specialist", "Data Entry Specialist"),
    ("i_t_technician", "IT Technician"),
    ("tax_preparer", "Tax Preparer"),
    ("billing", "Billing Agent"),
    ("reviewer", "Reviewer"),
    ("manager", "Manager"),
    ("owner", "Owner"),
)


@dataclass(frozen=True)
class RoleDemoSeedResult:
    organization: Organization
    superuser_updated: bool
    users_created: int
    users_updated: int


def _role_demo_email(role: str) -> str:
    return f"{role}@pdkentrust.com"


def ensure_superuser_profile() -> bool:
    """Ensure Rick's superuser/developer profile fields without changing password."""
    user = User.objects.filter(email=SUPERUSER_EMAIL).first()
    if user is None:
        return False

    changed = False
    for field, value in (
        ("first_name", SUPERUSER_FIRST_NAME),
        ("last_name", SUPERUSER_LAST_NAME),
        ("role", "developer"),
        ("is_superuser", True),
        ("is_staff", True),
        ("is_active", True),
    ):
        if getattr(user, field) != value:
            setattr(user, field, value)
            changed = True

    if changed:
        user.save()
    return changed


def seed_role_demos(
    *,
    password: str,
    reset_passwords: bool = False,
) -> RoleDemoSeedResult:
    """
    Idempotent QA seed: org, role demo users at role@pdkentrust.com, superuser profile.

    Passwords change when reset_passwords=True or the user was just created.
    """
    if not password:
        raise ValueError("password is required")

    org, _ = Organization.objects.get_or_create(name=DEMO_ORG_NAME)
    superuser_updated = ensure_superuser_profile()

    users_created = 0
    users_updated = 0
    for role, display_name in ROLE_DEMO_SPECS:
        email = _role_demo_email(role)
        user, created = User.objects.get_or_create(
            email=email,
            defaults={
                "organization": org,
                "role": role,
                "first_name": "Demo",
                "last_name": display_name,
                "is_staff": False,
                "is_superuser": False,
                "is_active": True,
            },
        )
        if created:
            user.set_password(password)
            user.save()
            users_created += 1
            continue

        changed = False
        for field, value in (
            ("organization", org),
            ("role", role),
            ("first_name", "Demo"),
            ("last_name", display_name),
            ("is_staff", False),
            ("is_superuser", False),
            ("is_active", True),
        ):
            if getattr(user, field) != value:
                setattr(user, field, value)
                changed = True

        if reset_passwords:
            user.set_password(password)
            changed = True

        if changed:
            user.save()
            users_updated += 1

    return RoleDemoSeedResult(
        organization=org,
        superuser_updated=superuser_updated,
        users_created=users_created,
        users_updated=users_updated,
    )
