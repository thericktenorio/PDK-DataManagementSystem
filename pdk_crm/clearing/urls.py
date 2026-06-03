from django.urls import path
from . import views


app_name = "clearing"


urlpatterns = [
    path("", views.clearing, name="clearing"),
    path("search_clients/", views.search_clients, name="search_clients"),
    path(
        "add_client_to_clearing/<int:client_id>/",
        views.add_client_to_clearing,
        name="add_client_to_clearing",
    ),
    path(
        "remove_client_from_clearing/<int:client_id>/",
        views.remove_client_from_clearing,
        name="remove_client_from_clearing",
    ),
    path(
        "add_product_assignment/",
        views.add_product_assignment,
        name="add_product_assignment",
    ),
    path(
        "remove_product_assignment/",
        views.remove_product_assignment,
        name="remove_product_assignment",
    ),
    path(
        "product-assignments/<int:pa_id>/complete/",
        views.complete_clearing,
        name="complete_clearing",
    ),
    path(
        "product-assignments/<int:pa_id>/reopen/",
        views.reopen_clearing,
        name="reopen_clearing",
    ),
    path(
        "product-assignments/<int:pa_id>/confirm-payment/",
        views.confirm_payment_received,
        name="confirm_payment_received",
    ),
    path(
        "product-assignments/<int:pa_id>/client-message/",
        views.client_message,
        name="client_message",
    ),
    path(
        "product-assignments/<int:pa_id>/parse-pdf/",
        views.parse_pdf_upload,
        name="parse_pdf_upload",
    ),
    path(
        "product-assignments/<int:pa_id>/parser-outputs/",
        views.parser_outputs,
        name="parser_outputs",
    ),
    path(
        "product-assignments/<int:pa_id>/parser-outputs/<str:kind>/",
        views.parser_output_download,
        name="parser_output_download",
    ),
]
