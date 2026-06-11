from core.backgrounds import sync_session_background


class AppBackgroundMiddleware:
    """Persist the user's daily background selection in the session."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            sync_session_background(request)
        return self.get_response(request)
