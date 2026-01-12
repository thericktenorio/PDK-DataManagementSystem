from django.urls import path
from . import views


app_name = "clearing"


urlpatterns = [
    path('', views.clearing, name = 'clearing'),
    path('search_clients/', views.search_clients, name = 'search_clients'),
    path('add_client_to_clearing/<int:client_id>/', views.add_client_to_clearing, name = 'add_client_to_clearing'),
    path('remove_client_from_clearing/<int:client_id>/', views.remove_client_from_clearing, name = 'remove_client_from_clearing'),
    path('add_product_assignment/', views.add_product_assignment, name = 'add_product_assignment'),
    path('remove_product_assignment/', views.remove_product_assignment, name = 'remove_product_assignment'),
    
    
]