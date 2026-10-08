from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    fieldsets = BaseUserAdmin.fieldsets + (
        ("Role & Profile", {"fields": ("role_name", "name")}),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ("Role & Profile", {"fields": ("role_name", "name")}),
    )
    list_display = ("username", "email", "role_name", "is_staff", "is_superuser")