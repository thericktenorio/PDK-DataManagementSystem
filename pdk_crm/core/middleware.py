from django.contrib import messages
from django.shortcuts import redirect

from core.backgrounds import sync_session_background
from core.nav_permissions import PROTECTED_NAV_VIEW_NAMES, user_can_access_nav_view


class NavRoleAccessMiddleware:
    """Redirect users who hit a main nav page URL their role cannot access."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        if not request.user.is_authenticated:
            return None

        match = request.resolver_match
        if not match or match.view_name not in PROTECTED_NAV_VIEW_NAMES:
            return None

        if user_can_access_nav_view(request.user, match.view_name):
            return None

        messages.warning(request, "You do not have access to that page.")
        return redirect("core:home")


class AppBackgroundMiddleware:
    """Persist the user's daily background selection in the session."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            sync_session_background(request)
        return self.get_response(request)
