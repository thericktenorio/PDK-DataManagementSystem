from core.backgrounds import get_background, sync_session_background, user_rotate_background_enabled


def app_background(request):
    key = sync_session_background(request)
    background = get_background(key)
    return {
        "app_background_key": background.key,
        "app_background_static": background.static_path,
        "rotate_background_enabled": user_rotate_background_enabled(request.user),
    }


def nav_apps(request):
    """Dock items and navbar welcome message — filtered by role (see core.nav_permissions)."""
    apps: list = []
    review_queue_count = 0
    nav_welcome_message = ""

    if request.user.is_authenticated:
        from core.nav_permissions import nav_apps_for_user, nav_welcome_message as build_welcome

        apps = nav_apps_for_user(request.user)
        nav_welcome_message = build_welcome(request.user)

        from review.selectors import review_queue_count as _review_queue_count

        review_urls = {app["url"] for app in apps if app.get("badge_key") == "review"}
        if review_urls:
            review_queue_count = _review_queue_count()

    return {
        "apps": apps,
        "review_queue_count": review_queue_count,
        "nav_welcome_message": nav_welcome_message,
    }