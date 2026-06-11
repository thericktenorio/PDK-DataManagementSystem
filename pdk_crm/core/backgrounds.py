from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone

MIN_BACKGROUND_WIDTH_PX = 2400


@dataclass(frozen=True)
class AppBackground:
    key: str
    static_path: str
    label: str


# Curated landscape coastal set — bright/airy scenes that work with the glass overlay.
# All assets stored at up to 3840px wide (see static/images/backgrounds/).
BACKGROUNDS: tuple[AppBackground, ...] = (
    AppBackground(
        key="beach-seagulls",
        static_path="images/backgrounds/beach-seagulls.jpg",
        label="Beach and seagulls",
    ),
    AppBackground(
        key="sd-golden-shoreline",
        static_path="images/backgrounds/sd-golden-shoreline.jpg",
        label="San Diego golden shoreline",
    ),
    AppBackground(
        key="bright-beach-day",
        static_path="images/backgrounds/bright-beach-day.jpg",
        label="Bright beach day",
    ),
    AppBackground(
        key="la-jolla-sunset-beach",
        static_path="images/backgrounds/la-jolla-sunset-beach.jpg",
        label="La Jolla sunset beach",
    ),
    AppBackground(
        key="la-jolla-cove-cliff",
        static_path="images/backgrounds/la-jolla-cove-cliff.jpg",
        label="La Jolla Cove cliffs",
    ),
    AppBackground(
        key="la-jolla-waves",
        static_path="images/backgrounds/la-jolla-waves.jpg",
        label="La Jolla waves",
    ),
    AppBackground(
        key="torrey-pines",
        static_path="images/backgrounds/torrey-pines.jpg",
        label="Torrey Pines coast",
    ),
    AppBackground(
        key="sd-harbor",
        static_path="images/backgrounds/sd-harbor.jpg",
        label="San Diego harbor",
    ),
)

BACKGROUND_BY_KEY = {entry.key: entry for entry in BACKGROUNDS}
DEFAULT_BACKGROUND_KEY = BACKGROUNDS[0].key
FIXED_BACKGROUND_KEY = "beach-seagulls"

SESSION_DATE_KEY = "app_background_date"
SESSION_BACKGROUND_KEY = "app_background_key"


def firm_localdate() -> date:
    tz = ZoneInfo(getattr(settings, "FIRM_TIME_ZONE", "America/Los_Angeles"))
    return timezone.now().astimezone(tz).date()


def select_background_key(user_id: int, on_date: date | None = None) -> str:
    """Deterministic daily pick — stable for a user on a given calendar day."""
    on_date = on_date or firm_localdate()
    if not BACKGROUNDS:
        return DEFAULT_BACKGROUND_KEY
    idx = (int(user_id) + on_date.toordinal()) % len(BACKGROUNDS)
    return BACKGROUNDS[idx].key


def get_background(key: str | None) -> AppBackground:
    if key and key in BACKGROUND_BY_KEY:
        return BACKGROUND_BY_KEY[key]
    return BACKGROUND_BY_KEY[DEFAULT_BACKGROUND_KEY]


def user_rotate_background_enabled(user) -> bool:
    return bool(getattr(user, "is_authenticated", False) and getattr(user, "rotate_background", False))


def sync_session_background(request) -> str:
    """
    Hybrid daily rotation: reuse the same background all day, refresh on a new
    calendar day (firm timezone). Returns the active background key.
    """
    if not user_rotate_background_enabled(request.user):
        return FIXED_BACKGROUND_KEY

    today = firm_localdate()
    today_iso = today.isoformat()

    if request.user.is_authenticated:
        if (
            request.session.get(SESSION_DATE_KEY) == today_iso
            and request.session.get(SESSION_BACKGROUND_KEY) in BACKGROUND_BY_KEY
        ):
            return request.session[SESSION_BACKGROUND_KEY]

        key = select_background_key(request.user.pk, today)
        request.session[SESSION_DATE_KEY] = today_iso
        request.session[SESSION_BACKGROUND_KEY] = key
        return key

    return select_background_key(0, today)
