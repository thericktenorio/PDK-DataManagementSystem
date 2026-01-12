# pdf_manager/pdf_manager/urls.py
from django.urls import path

from . import views

app_name = "ui"


urlpatterns = [
    path("", views.UploadView.as_view(), name="upload"),
    path("results/<uuid:job_id>/", views.ResultsView.as_view(), name="results"),
    path("history/", views.HistoryView.as_view(), name="history"),
]
