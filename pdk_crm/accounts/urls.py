from django.urls import path
from django.contrib.auth.views import LoginView, LogoutView

from accounts.forms import PlaceholderLoginForm
from accounts.password_reset_views import (
    AuthenticatorSetupConfirmView,
    AuthenticatorSetupView,
    PasswordResetCompleteView,
    PasswordResetConfirmView,
    PasswordResetRequestView,
    PasswordResetEnrollAuthenticatorView,
    PasswordResetVerifyEmailView,
    PasswordResetVerifyTotpView,
)


app_name = 'accounts'   # Required for namespace


urlpatterns = [
    path(
        'login/',
        LoginView.as_view(
            template_name='accounts/login.html',
            authentication_form=PlaceholderLoginForm,
        ),
        name='login',
    ),
    path('logout/', LogoutView.as_view(next_page = 'accounts:login'), name = 'logout'),
    path('password-reset/', PasswordResetRequestView.as_view(), name='password_reset'),
    path(
        'password-reset/verify-email/<uuid:challenge_id>/',
        PasswordResetVerifyEmailView.as_view(),
        name='password_reset_verify_email',
    ),
    path(
        'password-reset/enroll-authenticator/<uuid:challenge_id>/',
        PasswordResetEnrollAuthenticatorView.as_view(),
        name='password_reset_enroll_authenticator',
    ),
    path(
        'password-reset/verify-totp/<uuid:challenge_id>/',
        PasswordResetVerifyTotpView.as_view(),
        name='password_reset_verify_totp',
    ),
    path(
        'password-reset/confirm/<uuid:challenge_id>/',
        PasswordResetConfirmView.as_view(),
        name='password_reset_confirm',
    ),
    path(
        'password-reset/complete/',
        PasswordResetCompleteView.as_view(),
        name='password_reset_complete',
    ),
    path('authenticator/setup/', AuthenticatorSetupView.as_view(), name='authenticator_setup'),
    path(
        'authenticator/setup/confirm/',
        AuthenticatorSetupConfirmView.as_view(),
        name='authenticator_setup_confirm',
    ),
]