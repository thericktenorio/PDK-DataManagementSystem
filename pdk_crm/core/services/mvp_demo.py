"""MacBook MVP trial seed data (Phase 10.MVP). Dev/demo only — not for office prod."""
from __future__ import annotations

import datetime
from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.utils import timezone

from core.models import Client, Organization, TaxSeason
from intake.services.enrollment import enroll_client_in_intake

User = get_user_model()

DEMO_ORG_NAME = "PDK Tax Demo"
DEMO_CLIENT_TIN = "900000001"
DEMO_CLIENT_NAME = "Demo Client (MVP)"

DEMO_USERS: tuple[dict[str, str], ...] = (
    {"email": "developer@demo.pdk.local", "role": "developer", "first_name": "Dev", "last_name": "Admin"},
    {"email": "preparer@demo.pdk.local", "role": "tax_preparer", "first_name": "Pat", "last_name": "Preparer"},
    {"email": "reviewer@demo.pdk.local", "role": "reviewer", "first_name": "Riley", "last_name": "Reviewer"},
    {"email": "manager@demo.pdk.local", "role": "manager", "first_name": "Morgan", "last_name": "Manager"},
)

DEMO_USER_EMAILS = frozenset(u["email"] for u in DEMO_USERS)


@dataclass(frozen=True)
class MvpDemoSeedResult:
    organization: Organization
    tax_season: TaxSeason
    users_created: int
    users_updated: int
    sample_client: Client | None


def _active_tax_season_defaults() -> dict:
    calendar_year = timezone.now().year
    return {
        "year": calendar_year,
        "start_date": datetime.date(calendar_year, 1, 1),
        "end_date": datetime.date(calendar_year, 10, 15),
        "is_active": True,
    }


def seed_mvp_demo(
    *,
    password: str,
    with_sample_client: bool = False,
    reset_passwords: bool = False,
) -> MvpDemoSeedResult:
    """
    Idempotent demo seed: org, active tax season, role-based users.

    Re-running updates user profile fields; passwords change only when reset_passwords=True
    or the user was just created.
    """
    if not password:
        raise ValueError("password is required")

    org, _ = Organization.objects.get_or_create(name=DEMO_ORG_NAME)

    season_defaults = _active_tax_season_defaults()
    tax_season, created_season = TaxSeason.objects.get_or_create(
        year=season_defaults["year"],
        defaults=season_defaults,
    )
    if not created_season:
        TaxSeason.objects.filter(pk=tax_season.pk).update(
            start_date=season_defaults["start_date"],
            end_date=season_defaults["end_date"],
            is_active=True,
        )
        tax_season.refresh_from_db()

    users_created = 0
    users_updated = 0
    for spec in DEMO_USERS:
        user, created = User.objects.get_or_create(
            email=spec["email"],
            defaults={
                "organization": org,
                "role": spec["role"],
                "first_name": spec["first_name"],
                "last_name": spec["last_name"],
                "is_staff": spec["role"] == "developer",
                "is_superuser": spec["role"] == "developer",
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
            ("role", spec["role"]),
            ("first_name", spec["first_name"]),
            ("last_name", spec["last_name"]),
            ("is_staff", spec["role"] == "developer"),
            ("is_superuser", spec["role"] == "developer"),
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

    sample_client: Client | None = None
    if with_sample_client:
        sample_client, _ = Client.objects.get_or_create(
            TIN=DEMO_CLIENT_TIN,
            defaults={
                "name": DEMO_CLIENT_NAME,
                "email": "demo.client@example.com",
                "phone": "5555550100",
            },
        )
        enroll_client_in_intake(sample_client)

    return MvpDemoSeedResult(
        organization=org,
        tax_season=tax_season,
        users_created=users_created,
        users_updated=users_updated,
        sample_client=sample_client,
    )


def mvp_demo_readiness_issues() -> list[str]:
    """Return human-readable blockers for MacBook MVP demo readiness."""
    issues: list[str] = []

    if not Organization.objects.filter(name=DEMO_ORG_NAME).exists():
        issues.append(f'Missing organization "{DEMO_ORG_NAME}" — run seed_mvp_demo.')

    season = TaxSeason.objects.filter(is_active=True).order_by("-year").first()
    if season is None:
        issues.append("No active tax season — run seed_mvp_demo.")
    elif season.year != timezone.now().year:
        issues.append(
            f"Active tax season year is {season.year}; expected {timezone.now().year} for current calendar year."
        )

    missing_roles = []
    for spec in DEMO_USERS:
        if not User.objects.filter(email=spec["email"], is_active=True).exists():
            missing_roles.append(spec["role"])
    if missing_roles:
        issues.append(f"Missing demo users for roles: {', '.join(missing_roles)}.")

    return issues
