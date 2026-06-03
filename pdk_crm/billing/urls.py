from django.urls import path
from . import views


app_name = "billing"


urlpatterns = [
    path('', views.billing, name = 'billing'),
    path("invoices/<uuid:invoice_id>/send/", views.send_draft_invoice, name="send_draft_invoice"),
    path("qbo/connect/", views.qbo_connect, name = "qbo_connect"),
    path("qbo/callback/", views.qbo_callback, name = "qbo_callback"),
    path("qbo/webhook/", views.qbo_webhook, name = "qbo_webhook"),
    path("qbo/smoke/", views.qbo_smoke, name = "qbo_smoke"),
    path("invoices/create_send/", views.create_send_invoice_view, name = "create_send_invoice"),
    path("triggers/send_invoice_now/", views.send_invoice_now,name = "send_invoice_now"),
]