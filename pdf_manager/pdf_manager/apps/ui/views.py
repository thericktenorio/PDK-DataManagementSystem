from django.views.generic import TemplateView

from pdf_manager.apps.core.models import ParseJob


class UploadView(TemplateView):
    template_name = "ui/upload.html"


class ResultsView(TemplateView):
    template_name = "ui/results.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # job_id comes from urls.py: results/<uuid:job_id>/
        context["job_id"] = str(kwargs["job_id"])
        return context


class HistoryView(TemplateView):
    template_name = "ui/history.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["jobs"] = ParseJob.objects.select_related("document").order_by("-created_at")[:50]
        return context
