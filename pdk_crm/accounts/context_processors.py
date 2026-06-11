LOGIN_SURFACE_VIEWS = frozenset(
    {
        "accounts:login",
        "accounts:password_reset",
        "accounts:password_reset_verify_email",
        "accounts:password_reset_enroll_authenticator",
        "accounts:password_reset_verify_totp",
        "accounts:password_reset_confirm",
        "accounts:password_reset_complete",
        "accounts:authenticator_setup",
        "accounts:authenticator_setup_confirm",
    }
)


def login_surface(request):
    view_name = getattr(getattr(request, "resolver_match", None), "view_name", "")
    return {"is_login_surface": view_name in LOGIN_SURFACE_VIEWS}
