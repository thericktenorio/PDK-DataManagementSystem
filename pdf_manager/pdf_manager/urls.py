from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("pdf_manager.apps.core.urls")),
    path("", include("pdf_manager.apps.ui.urls", namespace="ui")),
    path("api/", include("pdf_manager.apps.ui.urls_api", namespace="ui_api")),
]
