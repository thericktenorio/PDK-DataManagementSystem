import re

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _


SPECIAL_CHAR_PATTERN = re.compile(r"[!@#$%^&*()_+\-=\[\]{}|;:,.<>?]")
PASSWORD_MIN_LENGTH = 8


class SpecialCharacterValidator:
    """Require at least one non-alphanumeric special character."""

    def validate(self, password, user=None):
        if not SPECIAL_CHAR_PATTERN.search(password):
            raise ValidationError(
                _("Password must include at least one special character."),
                code="password_no_special",
            )

    def get_help_text(self):
        return _("Your password must include at least one special character.")


def password_strength_label(password: str) -> str:
    """Return weak | moderate | strong | very_strong for UI feedback."""
    if not password:
        return "weak"

    score = 0
    if len(password) >= PASSWORD_MIN_LENGTH:
        score += 1
    if len(password) >= 12:
        score += 1
    if re.search(r"[a-z]", password) and re.search(r"[A-Z]", password):
        score += 1
    if re.search(r"\d", password):
        score += 1
    if SPECIAL_CHAR_PATTERN.search(password):
        score += 1

    if score <= 2:
        return "weak"
    if score == 3:
        return "moderate"
    if score == 4:
        return "strong"
    return "very_strong"
