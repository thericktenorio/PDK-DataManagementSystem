from functools import wraps

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden

ANALYTICS_ACCESS_ROLES = frozenset({
    "manager",
    "owner",
    "developer",
})


def user_can_access_analytics(user) -> bool:
    return user.is_authenticated and getattr(user, "role", None) in ANALYTICS_ACCESS_ROLES


def analytics_access_required(view_func):
    @login_required
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not user_can_access_analytics(request.user):
            return HttpResponseForbidden("You do not have access to analytics.")
        return view_func(request, *args, **kwargs)

    return wrapper
