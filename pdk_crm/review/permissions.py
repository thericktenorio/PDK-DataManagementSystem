from functools import wraps

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden

REVIEW_ACCESS_ROLES = frozenset({
    "tax_preparer",
    "billing",
    "reviewer",
    "manager",
    "owner",
    "developer",
})


def user_can_access_review(user) -> bool:
    return user.is_authenticated and getattr(user, "role", None) in REVIEW_ACCESS_ROLES


def review_access_required(view_func):
    @login_required
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not user_can_access_review(request.user):
            return HttpResponseForbidden("You do not have access to the review module.")
        return view_func(request, *args, **kwargs)

    return wrapper
