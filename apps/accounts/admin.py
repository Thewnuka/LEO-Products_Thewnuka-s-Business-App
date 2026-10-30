from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import AccountAuditLog, User


@admin.register(User)
class LeoUserAdmin(UserAdmin):
    """
    Django admin is available to OWNER accounts only (is_staff follows the role).
    is_staff / is_superuser are derived from the role and shown read-only.
    """

    list_display = ("username", "email", "first_name", "last_name", "role", "is_active", "is_primary_owner")
    list_filter = ("role", "is_active", "is_primary_owner")
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Personal info", {"fields": ("first_name", "last_name", "email", "phone_number")}),
        ("Role & status", {"fields": ("role", "is_active", "must_change_password", "is_primary_owner",
                                      "is_staff", "is_superuser")}),
        ("Fine-grained permissions (future phases)", {"classes": ("collapse",), "fields": ("groups", "user_permissions")}),
        ("Record", {"fields": ("last_login", "date_joined", "updated_at")}),
    )
    readonly_fields = ("is_staff", "is_superuser", "is_primary_owner", "last_login", "date_joined", "updated_at")

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if obj is not None and obj.is_primary_owner:
            fields += ["role", "is_active"]
        return fields

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.is_primary_owner:
            return False
        return super().has_delete_permission(request, obj)


@admin.register(AccountAuditLog)
class AccountAuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "action", "actor", "target", "ip_address")
    list_filter = ("action",)
    search_fields = ("actor__username", "target__username")
    readonly_fields = ("created_at", "updated_at", "action", "actor", "target", "details", "ip_address")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
