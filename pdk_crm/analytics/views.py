from django.shortcuts import render
from django.views.decorators.cache import cache_control

from analytics.permissions import analytics_access_required
from analytics.selectors import get_dashboard_context


@analytics_access_required
@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def analytics(request):
    season_param = request.GET.get("season")
    season_year = None
    if season_param:
        try:
            season_year = int(season_param)
        except (TypeError, ValueError):
            season_year = None

    ctx = get_dashboard_context(season_year=season_year)
    return render(
        request,
        "analytics/analytics.html",
        {
            "page_title": "Analytics",
            "dashboard": ctx,
        },
    )
