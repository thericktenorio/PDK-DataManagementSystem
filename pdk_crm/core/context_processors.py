def nav_apps(request):
    '''
    Provides the pp dock items to all templates.
    Update list everytime the home screen list changes too
    '''

    return {
        "apps": [
            {"name": "Home", "icon": "icons/home.svg", "url": "core:home"},
            {"name": "Calendar", "icon": "icons/calendar.svg", "url": "pdk_calendar:pdk_calendar"},
            {"name": "Intake", "icon": "icons/intake.svg", "url": "intake:intake"},
            {"name": "Clearing", "icon": "icons/clearing.svg", "url": "clearing:clearing"},
            {"name": "Billing", "icon": "icons/billing.svg", "url": "billing:billing"},
            {"name": "Review", "icon": "icons/review.svg", "url": "review:review"},
            {"name": "Acknowledgments", "icon": "icons/acknowledgments.svg", "url": "acknowledgments:acknowledgments"},
            {"name": "Analytics", "icon": "icons/analytics.svg", "url": "analytics:analytics"},
            {"name": "Client Portfolio", "icon": "icons/client_portfolio.svg", "url": "client_portfolio:client_portfolio"},
        ]
    }