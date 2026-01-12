# pdf_manager/pdf_manager/apps/ui/urls_api.py
from django.urls import path

from . import api

app_name = "ui_api"


urlpatterns = [
    path("upload/", api.upload_api, name="upload"),
    path("jobs/<uuid:job_id>/", api.job_status_api, name="job_status"),
    path("jobs/<uuid:job_id>/output/", api.job_output_api, name="job_output"),
    path("jobs/<uuid:job_id>/outputs/", api.job_outputs_api, name="job_outputs"),
]
