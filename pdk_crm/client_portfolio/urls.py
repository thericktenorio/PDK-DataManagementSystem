from django.urls import path
from . import views


app_name = 'client_portfolio'


urlpatterns = [
    path('', views.client_portfolio, name = 'client_portfolio'),
    path('save/', views.create_and_save_new_client, name = 'save_client'),
    path('delete_client/<int:client_id>/', views.delete_client, name = 'delete_client'),
    path('import_clients/', views.import_clients, name = 'import_clients'),
]