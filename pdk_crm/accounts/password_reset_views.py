from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views import View

from accounts.forms import (
    AuthenticatorConfirmForm,
    AuthenticatorSetupForm,
    EmailCodeVerificationForm,
    PasswordResetConfirmForm,
    PasswordResetRequestForm,
    TotpVerificationForm,
)
from accounts.models import AuthenticatorDevice, PasswordResetChallenge
from accounts.services.password_reset import (
    complete_challenge,
    create_password_reset_challenge,
    mark_totp_verified,
    send_password_reset_admin_notice,
    send_password_reset_email,
    verify_email_code,
)
from accounts.services.totp import (
    get_or_create_pending_device,
    provisioning_uri,
    start_authenticator_enrollment,
    verify_totp_code,
    verify_user_totp,
)

User = get_user_model()


def _user_has_confirmed_authenticator(user) -> bool:
    device = getattr(user, "authenticator_device", None)
    return device is not None and device.is_confirmed


def _redirect_after_email_verified(challenge_id):
    challenge = PasswordResetChallenge.objects.select_related("user").get(pk=challenge_id)
    if _user_has_confirmed_authenticator(challenge.user):
        return redirect("accounts:password_reset_verify_totp", challenge_id=challenge_id)
    return redirect("accounts:password_reset_enroll_authenticator", challenge_id=challenge_id)


def _get_active_challenge(challenge_id) -> PasswordResetChallenge | None:
    challenge = (
        PasswordResetChallenge.objects.select_related("user")
        .filter(pk=challenge_id, completed_at__isnull=True)
        .first()
    )
    if challenge is None or challenge.is_expired:
        return None
    return challenge


class PasswordResetRequestView(View):
    template_name = "accounts/password_reset_request.html"

    def get(self, request):
        return render(request, self.template_name, {"form": PasswordResetRequestForm()})

    def post(self, request):
        form = PasswordResetRequestForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, {"form": form})

        email = form.cleaned_data["email"].strip().lower()
        user = User.objects.filter(email__iexact=email, is_active=True).first()
        if user is not None:
            challenge, email_code = create_password_reset_challenge(user=user)
            send_password_reset_email(user=user, email_code=email_code)
            send_password_reset_admin_notice(user=user)
            request.session["password_reset_challenge_id"] = str(challenge.id)
            return redirect("accounts:password_reset_verify_email", challenge_id=challenge.id)

        messages.info(
            request,
            "If an account exists for that email, verification instructions were sent.",
        )
        return redirect("accounts:login")


class PasswordResetVerifyEmailView(View):
    template_name = "accounts/password_reset_verify_email.html"

    def get(self, request, challenge_id):
        challenge = _get_active_challenge(challenge_id)
        if challenge is None:
            messages.error(request, "This reset link has expired. Start again.")
            return redirect("accounts:password_reset")

        return render(
            request,
            self.template_name,
            {"form": EmailCodeVerificationForm(), "challenge": challenge},
        )

    def post(self, request, challenge_id):
        challenge = _get_active_challenge(challenge_id)
        if challenge is None:
            messages.error(request, "This reset link has expired. Start again.")
            return redirect("accounts:password_reset")

        form = EmailCodeVerificationForm(request.POST)
        if not form.is_valid():
            return render(
                request,
                self.template_name,
                {"form": form, "challenge": challenge},
            )

        if not verify_email_code(challenge=challenge, code=form.cleaned_data["code"]):
            form.add_error("code", "Invalid or expired verification code.")
            return render(
                request,
                self.template_name,
                {"form": form, "challenge": challenge},
            )

        return _redirect_after_email_verified(challenge.id)


class PasswordResetEnrollAuthenticatorView(View):
    """Enroll TOTP during reset — email already verified; no current password needed."""

    template_name = "accounts/password_reset_enroll_authenticator.html"

    def _get_challenge(self, challenge_id) -> PasswordResetChallenge | None:
        challenge = _get_active_challenge(challenge_id)
        if challenge is None or challenge.email_verified_at is None:
            return None
        if _user_has_confirmed_authenticator(challenge.user):
            return None
        return challenge

    def get(self, request, challenge_id):
        challenge = self._get_challenge(challenge_id)
        if challenge is None:
            messages.error(request, "Complete email verification first.")
            return redirect("accounts:password_reset")

        device = get_or_create_pending_device(user=challenge.user)
        return render(
            request,
            self.template_name,
            {
                "form": AuthenticatorConfirmForm(),
                "challenge": challenge,
                "device": device,
                "provisioning_uri": provisioning_uri(user=challenge.user, secret=device.secret),
                "secret": device.secret,
            },
        )

    def post(self, request, challenge_id):
        challenge = self._get_challenge(challenge_id)
        if challenge is None:
            messages.error(request, "Complete email verification first.")
            return redirect("accounts:password_reset")

        device = get_or_create_pending_device(user=challenge.user)
        form = AuthenticatorConfirmForm(request.POST)
        if not form.is_valid():
            return render(
                request,
                self.template_name,
                {
                    "form": form,
                    "challenge": challenge,
                    "device": device,
                    "provisioning_uri": provisioning_uri(user=challenge.user, secret=device.secret),
                    "secret": device.secret,
                },
            )

        if not verify_totp_code(secret=device.secret, code=form.cleaned_data["code"]):
            form.add_error("code", "Invalid authenticator code.")
            return render(
                request,
                self.template_name,
                {
                    "form": form,
                    "challenge": challenge,
                    "device": device,
                    "provisioning_uri": provisioning_uri(user=challenge.user, secret=device.secret),
                    "secret": device.secret,
                },
            )

        device.confirmed_at = timezone.now()
        device.save(update_fields=["confirmed_at"])
        mark_totp_verified(challenge=challenge)
        messages.success(request, "Authenticator enrolled. Choose your new password.")
        return redirect("accounts:password_reset_confirm", challenge_id=challenge.id)


class PasswordResetVerifyTotpView(View):
    template_name = "accounts/password_reset_verify_totp.html"

    def get(self, request, challenge_id):
        challenge = _get_active_challenge(challenge_id)
        if challenge is None or challenge.email_verified_at is None:
            messages.error(request, "Complete email verification first.")
            return redirect("accounts:password_reset")
        if not _user_has_confirmed_authenticator(challenge.user):
            return redirect("accounts:password_reset_enroll_authenticator", challenge_id=challenge.id)

        return render(
            request,
            self.template_name,
            {"form": TotpVerificationForm(), "challenge": challenge},
        )

    def post(self, request, challenge_id):
        challenge = _get_active_challenge(challenge_id)
        if challenge is None or challenge.email_verified_at is None:
            messages.error(request, "Complete email verification first.")
            return redirect("accounts:password_reset")
        if not _user_has_confirmed_authenticator(challenge.user):
            return redirect("accounts:password_reset_enroll_authenticator", challenge_id=challenge.id)

        form = TotpVerificationForm(request.POST)
        if not form.is_valid():
            return render(
                request,
                self.template_name,
                {"form": form, "challenge": challenge},
            )

        if not verify_user_totp(user=challenge.user, code=form.cleaned_data["code"]):
            form.add_error("code", "Invalid authenticator code.")
            return render(
                request,
                self.template_name,
                {"form": form, "challenge": challenge},
            )

        mark_totp_verified(challenge=challenge)
        return redirect("accounts:password_reset_confirm", challenge_id=challenge.id)


class PasswordResetConfirmView(View):
    template_name = "accounts/password_reset_confirm.html"

    def get(self, request, challenge_id):
        challenge = _get_active_challenge(challenge_id)
        if challenge is None or challenge.totp_verified_at is None:
            messages.error(request, "Complete verification before choosing a new password.")
            return redirect("accounts:password_reset")

        return render(
            request,
            self.template_name,
            {
                "form": PasswordResetConfirmForm(user=challenge.user),
                "challenge": challenge,
            },
        )

    def post(self, request, challenge_id):
        challenge = _get_active_challenge(challenge_id)
        if challenge is None or challenge.totp_verified_at is None:
            messages.error(request, "Complete verification before choosing a new password.")
            return redirect("accounts:password_reset")

        form = PasswordResetConfirmForm(user=challenge.user, data=request.POST)
        if not form.is_valid():
            return render(
                request,
                self.template_name,
                {"form": form, "challenge": challenge},
            )

        form.save()
        complete_challenge(challenge=challenge)
        messages.success(request, "Your password has been reset. Sign in with your new password.")
        return redirect("accounts:password_reset_complete")


class PasswordResetCompleteView(View):
    template_name = "accounts/password_reset_complete.html"

    def get(self, request):
        return render(request, self.template_name)


class AuthenticatorSetupView(View):
    template_name = "accounts/authenticator_setup.html"

    def get(self, request):
        return render(request, self.template_name, {"form": AuthenticatorSetupForm()})

    def post(self, request):
        form = AuthenticatorSetupForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, {"form": form})

        user = form.cleaned_data["user"]
        device = getattr(user, "authenticator_device", None)
        if device is not None and device.is_confirmed:
            messages.info(request, "Authenticator is already set up for this account.")
            return redirect("accounts:login")

        device = start_authenticator_enrollment(user=user)
        request.session["authenticator_setup_user_id"] = user.pk
        return redirect("accounts:authenticator_setup_confirm")


class AuthenticatorSetupConfirmView(View):
    template_name = "accounts/authenticator_setup_confirm.html"

    def _get_pending_device(self, request) -> AuthenticatorDevice | None:
        user_id = request.session.get("authenticator_setup_user_id")
        if not user_id:
            return None
        return (
            AuthenticatorDevice.objects.select_related("user")
            .filter(user_id=user_id, confirmed_at__isnull=True)
            .first()
        )

    def get(self, request):
        device = self._get_pending_device(request)
        if device is None:
            messages.error(request, "Start authenticator setup again.")
            return redirect("accounts:authenticator_setup")

        return render(
            request,
            self.template_name,
            {
                "form": AuthenticatorConfirmForm(),
                "device": device,
                "provisioning_uri": provisioning_uri(user=device.user, secret=device.secret),
                "secret": device.secret,
            },
        )

    def post(self, request):
        device = self._get_pending_device(request)
        if device is None:
            messages.error(request, "Start authenticator setup again.")
            return redirect("accounts:authenticator_setup")

        form = AuthenticatorConfirmForm(request.POST)
        if not form.is_valid():
            return render(
                request,
                self.template_name,
                {
                    "form": form,
                    "device": device,
                    "provisioning_uri": provisioning_uri(user=device.user, secret=device.secret),
                    "secret": device.secret,
                },
            )

        if not verify_totp_code(secret=device.secret, code=form.cleaned_data["code"]):
            form.add_error("code", "Invalid authenticator code.")
            return render(
                request,
                self.template_name,
                {
                    "form": form,
                    "device": device,
                    "provisioning_uri": provisioning_uri(user=device.user, secret=device.secret),
                    "secret": device.secret,
                },
            )

        device.confirmed_at = timezone.now()
        device.save(update_fields=["confirmed_at"])
        request.session.pop("authenticator_setup_user_id", None)
        messages.success(request, "Authenticator enrolled. You can now reset your password if needed.")
        return redirect("accounts:login")
