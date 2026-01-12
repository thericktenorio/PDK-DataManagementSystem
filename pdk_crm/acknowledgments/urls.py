from django.urls import path
from . import views


app_name = "acknowledgments"


urlpatterns = [
    path('', views.acknowledgments, name = 'acknowledgments'),
    path('post/', views.post_acknowledgments, name='post'),
    path("resolve/", views.resolve_ack_staging, name = "resolve"),
]