from django.urls import path
from django.contrib.auth.views import LoginView, LogoutView


app_name = 'accounts'   # Required for namespace


urlpatterns = [
    path('login/', LoginView.as_view(template_name = 'accounts/login.html'), name = 'login'),
    path('logout/', LogoutView.as_view(next_page = 'accounts:login'), name = 'logout'),
]