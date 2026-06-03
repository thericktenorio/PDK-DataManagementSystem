from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import InternalUser


@admin.register(InternalUser)
class InternalUserAdmin(UserAdmin):
    model = InternalUser
    list_display = ['email', 'role', 'is_staff', 'is_active']
    list_filter = ['role', 'is_staff', 'is_active']
    search_fields = ['email', 'first_name', 'last_name']
    ordering = ['email']

    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Personal Info', {'fields': ('first_name', 'last_name', 'role', 'organization')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'user_permissions', 'groups')}),
        ('Important dates', {'fields': ('last_login', )}),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': (
                'email', 'first_name', 'last_name', 'organization', 'role',
                'password1', 'password2', 'is_staff', 'is_active', 'is_superuser',
            ),
        }),
    )