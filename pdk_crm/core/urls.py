from django.urls import path, include
from . import views
from .views import home_view
from django.contrib import admin
from django.urls import include


app_name = 'core'

urlpatterns = [
    # page urls
    path('', home_view, name = 'home'),
    path("pdk_calendar/", include("pdk_calendar.urls", namespace = "pdk_calendar")),
    path("intake/", include("intake.urls", namespace = "intake")),
    path("clearing/", include("clearing.urls", namespace = "clearing")),
    path("acknowledgments/", include("acknowledgments.urls", namespace = "acknowledgments")),
    path("review/", include("review.urls", namespace = "review")),
    path("billing/", include("billing.urls", namespace = "billing")),
    path("analytics/", include("analytics.urls", namespace = "analytics")),
    path("client_portfolio/", include("client_portfolio.urls", namespace = "client_portfolio")),

    # core function urls
    path('preferences/rotate-background/', views.update_rotate_background, name='update_rotate_background'),
    path('auto_save/', views.auto_save, name = 'auto_save'),
    # path('auto_save_tax_year/', views.auto_save_tax_year, name = 'auto_save_tax_year'),
    # path('auto_save_product/', views.auto_save_product, name = 'auto_save_product'),
    path('auto_save_product_assignment/', views.auto_save_product_assignment, name = 'auto_save_product_assignment'),
    path('archive_tax_season/', views.archive_tax_season, name = 'archive_tax_season'),

    path("clients/create-form-ack/", views.create_client_from_ack, name = "create_client_from_ack"),

    # completion workflow urls for PA that have been completed
    path("product-assignments/<int:pa_id>/start-completion/", views.start_completion, name = 'start_completion'),
    path("product-assignments/<int:pa_id>/skip_parser/", views.skip_parser, name = "skip_parser"),
    path("product-assignments/<int:pa_id>/begin_ack_count/", views.begin_ack_count, name = "begin_ack_count"),
    path("product-assignments/<int:pa_id>/set_expected_ack_count/", views.set_expected_ack_count, name = "set_expected_ack_count"),
    path("product-assignments/<int:pa_id>/finalize_completion/", views.finalize_completion, name = "finalize_completion"),
    path("product-assignments/<int:pa_id>/cancel_completion/", views.cancel_completion, name = 'cancel_completion'),
]