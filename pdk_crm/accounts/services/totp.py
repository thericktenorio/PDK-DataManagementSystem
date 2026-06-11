from __future__ import annotations

import pyotp

from accounts.models import AuthenticatorDevice, InternalUser


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(*, user: InternalUser, secret: str) -> str:
    issuer = "PDK ENTRUST"
    return pyotp.totp.TOTP(secret).provisioning_uri(name=user.email, issuer_name=issuer)


def verify_totp_code(*, secret: str, code: str) -> bool:
    normalized = (code or "").strip().replace(" ", "")
    if not normalized.isdigit() or len(normalized) != 6:
        return False
    totp = pyotp.TOTP(secret)
    return totp.verify(normalized, valid_window=1)


def verify_user_totp(*, user: InternalUser, code: str) -> bool:
    device = getattr(user, "authenticator_device", None)
    if device is None or not device.is_confirmed:
        return False
    return verify_totp_code(secret=device.secret, code=code)


def get_or_create_pending_device(*, user: InternalUser) -> AuthenticatorDevice:
    """Return an unconfirmed device, creating one if needed. Reuses an in-progress secret."""
    device = AuthenticatorDevice.objects.filter(user=user).first()
    if device is not None:
        if device.is_confirmed:
            raise ValueError("Authenticator is already enrolled for this account.")
        return device

    return AuthenticatorDevice.objects.create(
        user=user,
        secret=generate_totp_secret(),
    )


def start_authenticator_enrollment(*, user: InternalUser) -> AuthenticatorDevice:
    """Start proactive authenticator setup; issues a fresh secret for each attempt."""
    device = AuthenticatorDevice.objects.filter(user=user).first()
    if device is not None and device.is_confirmed:
        raise ValueError("Authenticator is already enrolled for this account.")

    secret = generate_totp_secret()
    if device is None:
        return AuthenticatorDevice.objects.create(user=user, secret=secret)

    device.secret = secret
    device.confirmed_at = None
    device.save(update_fields=["secret", "confirmed_at"])
    return device
