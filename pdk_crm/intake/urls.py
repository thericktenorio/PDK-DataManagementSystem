from django.urls import path
from . import views


app_name = "intake"


urlpatterns = [
    path('', views.intake, name = 'intake'),
    path('search_clients/', views.search_clients, name = 'search_clients'),
    path('add_client_to_intake/<int:client_id>/', views.add_client_to_intake, name = 'add_client_to_intake'),
    path('remove_client_from_intake/<int:client_id>/', views.remove_client_from_intake, name = 'remove_client_from_intake'),
    path('create_new_client/', views.create_new_client, name = 'create_new_client'),
    path('add_product_assignment/', views.add_product_assignment, name = 'add_product_assignment'),
    path('cancel_product_assignment/', views.cancel_product_assignment, name = 'cancel_product_assignment'),
    
]