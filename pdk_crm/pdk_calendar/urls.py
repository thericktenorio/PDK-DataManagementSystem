from django.urls import path
from . import views


app_name = "pdk_calendar"


urlpatterns = [
    path('', views.pdk_calendar, name = 'pdk_calendar'),
]