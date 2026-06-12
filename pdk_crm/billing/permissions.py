from functools import wraps

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, JsonResponse

from core.nav_permissions import FULL_ACCESS_ROLES


def user_can_manage_billing_settings(user) -> bool:
    return user.is_authenticated and getattr(user, "role", None) in FULL_ACCESS_ROLES


def billing_settings_required(view_func):
    @login_required
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not user_can_manage_billing_settings(request.user):
            return HttpResponseForbidden("You do not have permission to change billing settings.")
        return view_func(request, *args, **kwargs)

    return wrapper


def billing_settings_required_json(view_func):
    @login_required
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not user_can_manage_billing_settings(request.user):
            return JsonResponse(
                {"status": "error", "message": "You do not have permission to change billing settings."},
                status=403,
            )
        return view_func(request, *args, **kwargs)

    return wrapper
