def nav_apps(request):
    '''
    Provides the pp dock items to all templates.
    Update list everytime the home screen list changes too
    '''

    apps = [
        {"name": "Home", "icon": "icons/home.svg", "url": "core:home"},
        {"name": "Calendar", "icon": "icons/calendar.svg", "url": "pdk_calendar:pdk_calendar"},
        {"name": "Intake", "icon": "icons/intake.svg", "url": "intake:intake"},
        {"name": "Clearing", "icon": "icons/clearing.svg", "url": "clearing:clearing"},
        {"name": "Billing", "icon": "icons/billing.svg", "url": "billing:billing"},
        {"name": "Review", "icon": "icons/review.svg", "url": "review:review", "badge_key": "review"},
        {"name": "Acknowledgments", "icon": "icons/acknowledgments.svg", "url": "acknowledgments:acknowledgments"},
        {"name": "Client Portfolio", "icon": "icons/client_portfolio.svg", "url": "client_portfolio:client_portfolio"},
    ]

    review_queue_count = 0
    if request.user.is_authenticated:
        from review.permissions import user_can_access_review
        from review.selectors import review_queue_count as _review_queue_count

        if user_can_access_review(request.user):
            review_queue_count = _review_queue_count()

        from analytics.permissions import user_can_access_analytics

        if user_can_access_analytics(request.user):
            apps.insert(
                -1,
                {"name": "Analytics", "icon": "icons/analytics.svg", "url": "analytics:analytics"},
            )

    return {
        "apps": apps,
        "review_queue_count": review_queue_count,
    }