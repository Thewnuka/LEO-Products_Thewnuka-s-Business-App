"""Read-only order records in the admin; orders are managed in the staff portal (Orders)."""
from django.contrib import admin

from .models import CheckoutSettings, DeliveryZone, Order, OrderItem, OrderStatusEvent


class ReadOnlyInline(admin.TabularInline):
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class OrderItemInline(ReadOnlyInline):
    model = OrderItem
    fields = ("product_name", "variation_name", "sku", "unit_price", "quantity", "line_total")


class StatusEventInline(ReadOnlyInline):
    model = OrderStatusEvent
    fields = ("created_at", "from_status", "to_status", "note", "created_by")
    readonly_fields = fields


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("number", "full_name", "status", "payment_method", "payment_status", "total", "created_at")
    list_filter = ("status", "payment_method", "payment_status", "fulfilment")
    search_fields = ("number", "full_name", "phone", "email")
    inlines = [OrderItemInline, StatusEventInline]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(DeliveryZone)
class DeliveryZoneAdmin(admin.ModelAdmin):
    list_display = ("name", "fee", "free_delivery_over", "is_active", "sort_order")

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CheckoutSettings)
class CheckoutSettingsAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return not CheckoutSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
