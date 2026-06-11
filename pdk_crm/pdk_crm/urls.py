"""
URL configuration for pdk_crm project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from core.views import health

urlpatterns = [
    path('health/', health, name='health'),
    path('admin/', admin.site.urls),
    path('', include(('core.urls', 'core'), namespace = 'core')),
    path('accounts/', include(('accounts.urls', 'accounts'), namespace = 'accounts')),
    path('calendar/', include(('pdk_calendar.urls', 'pdk_calendar'), namespace = 'calendar')),
    path('intake/', include(('intake.urls', 'intake'), namespace = 'intake')),
    path('clearing/', include(('clearing.urls', 'clearing'), namespace = 'clearing')),
    path('acknowledgments/', include(('acknowledgments.urls', 'acknowledgments'), namespace = 'acknowledgments' )),
    path('review/', include(('review.urls', 'review'), namespace = 'review')),
    path('billing/', include(('billing.urls', 'billing'), namespace = 'billing')),
    path('analytics/', include(('analytics.urls', 'analytics'), namespace = 'analytics')),
    path('client_portfolio/', include(('client_portfolio.urls', 'client_portfolio') ,namespace = 'client_portfolio')),
]
