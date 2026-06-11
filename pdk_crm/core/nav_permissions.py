"""Role-based navigation and main-page access (home grid + dock)."""
from __future__ import annotations

from typing import Any

NAV_APP_SPECS: tuple[dict[str, str], ...] = (
    {"key": "home", "name": "Home", "icon": "icons/home.svg", "url_name": "core:home"},
    {"key": "calendar", "name": "Calendar", "icon": "icons/calendar.svg", "url_name": "pdk_calendar:pdk_calendar"},
    {"key": "intake", "name": "Intake", "icon": "icons/intake.svg", "url_name": "intake:intake"},
    {"key": "clearing", "name": "Clearing", "icon": "icons/clearing.svg", "url_name": "clearing:clearing"},
    {"key": "billing", "name": "Billing", "icon": "icons/billing.svg", "url_name": "billing:billing"},
    {"key": "review", "name": "Review", "icon": "icons/review.svg", "url_name": "review:review"},
    {"key": "acknowledgments", "name": "Acknowledgments", "icon": "icons/acknowledgments.svg", "url_name": "acknowledgments:acknowledgments"},
    {"key": "analytics", "name": "Analytics", "icon": "icons/analytics.svg", "url_name": "analytics:analytics"},
    {"key": "client_portfolio", "name": "Client Portfolio", "icon": "icons/client_portfolio.svg", "url_name": "client_portfolio:client_portfolio"},
)

ALL_NAV_KEYS = frozenset(spec["key"] for spec in NAV_APP_SPECS)

ROLE_NAV_KEYS: dict[str, frozenset[str]] = {
    "office_admin": frozenset({"home", "calendar", "intake", "client_portfolio"}),
    "data_entry_specialist": frozenset({"home", "calendar", "intake"}),
    "i_t_technician": frozenset({"home", "calendar"}),
    "tax_preparer": frozenset({"home", "calendar", "intake", "clearing"}),
    "billing": frozenset({"home", "calendar", "billing"}),
    "reviewer": frozenset({
        "home",
        "calendar",
        "intake",
        "clearing",
        "billing",
        "review",
        "acknowledgments",
    }),
    "manager": ALL_NAV_KEYS,
    "owner": ALL_NAV_KEYS,
    "developer": ALL_NAV_KEYS,
}

FULL_ACCESS_ROLES = frozenset({"manager", "owner", "developer"})

PROTECTED_NAV_VIEW_NAMES = frozenset(spec["url_name"] for spec in NAV_APP_SPECS)

_URL_NAME_TO_KEY = {spec["url_name"]: spec["key"] for spec in NAV_APP_SPECS}


def nav_keys_for_role(role: str | None) -> frozenset[str]:
    if role in FULL_ACCESS_ROLES:
        return ALL_NAV_KEYS
    return ROLE_NAV_KEYS.get(role or "", frozenset({"home"}))


def user_can_access_nav_view(user, view_name: str) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    key = _URL_NAME_TO_KEY.get(view_name)
    if key is None:
        return True
    return key in nav_keys_for_role(getattr(user, "role", None))


def nav_apps_for_user(user) -> list[dict[str, Any]]:
    """Dock/home app entries filtered by role."""
    allowed = nav_keys_for_role(getattr(user, "role", None))
    apps: list[dict[str, Any]] = []
    for spec in NAV_APP_SPECS:
        if spec["key"] not in allowed:
            continue
        entry: dict[str, Any] = {
            "name": spec["name"],
            "icon": spec["icon"],
            "url": spec["url_name"],
        }
        if spec["key"] == "review":
            entry["badge_key"] = "review"
        apps.append(entry)
    return apps


def nav_welcome_first_name(user) -> str:
    first = (getattr(user, "first_name", "") or "").strip()
    if first:
        return first
    last = (getattr(user, "last_name", "") or "").strip()
    if last:
        return last
    email = (getattr(user, "email", "") or "").strip()
    if email and "@" in email:
        return email.split("@", 1)[0]
    return "User"


def nav_welcome_message(user) -> str:
    role_label = getattr(user, "get_role_display", lambda: getattr(user, "role", ""))()
    return f"Welcome, {nav_welcome_first_name(user)} ({role_label})"
