import json

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_POST

from analytics.permissions import (
    agent_access_required,
    analytics_access_required,
    user_can_access_agent,
)
from analytics.selectors import get_dashboard_context
from analytics.services.agent import AgentError, agent_enabled, ask_agent


@analytics_access_required
@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def analytics(request):
    ctx = get_dashboard_context()
    return render(
        request,
        "analytics/analytics.html",
        {
            "page_title": "Analytics",
            "dashboard": ctx,
            "agent_enabled": agent_enabled(),
            "agent_access": user_can_access_agent(request.user),
        },
    )


@agent_access_required
@require_POST
def analytics_ask(request):
    if not agent_enabled():
        return JsonResponse(
            {"status": "error", "message": "Analytics agent is disabled."},
            status=503,
        )

    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse(
            {"status": "error", "message": "Invalid JSON body."},
            status=400,
        )

    question = (data.get("question") or "").strip()
    if not question:
        return JsonResponse(
            {"status": "error", "message": "Question is required."},
            status=400,
        )
    if len(question) > 2000:
        return JsonResponse(
            {"status": "error", "message": "Question is too long."},
            status=400,
        )

    try:
        result = ask_agent(question, user=request.user)
    except AgentError as exc:
        return JsonResponse({"status": "error", "message": str(exc)}, status=400)
    except Exception as exc:
        return JsonResponse(
            {"status": "error", "message": f"Agent failed unexpectedly: {exc}"},
            status=500,
        )

    return JsonResponse({
        "status": "success",
        "answer": result.answer,
        "sql": result.sql,
        "columns": result.columns,
        "rows": result.rows,
        "chart": result.chart,
        "coverage_note": result.coverage_note,
        "etl_as_of": result.etl_as_of,
        "audit_id": result.audit_id,
        "model": getattr(settings, "AGENT_LLM_MODEL", "gpt-4o-mini"),
    })
