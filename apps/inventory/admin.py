"""
Read-mostly admin views. Stock quantities and the movement ledger cannot be
edited here: stock changes only through the inventory screens (services.py).
"""
from django.contrib import admin

from .models import InventoryItem, Purchase, PurchaseLine, StockMovement, Supplier


class NoDeleteMixin:
    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(InventoryItem)
class InventoryItemAdmin(NoDeleteMixin, admin.ModelAdmin):
    list_display = ("__str__", "kind", "quantity", "reorder_level", "is_active", "last_movement_at")
    list_filter = ("kind", "is_active")
    search_fields = ("name", "variation__product__name", "variation__sku")
    readonly_fields = ("quantity", "last_movement_at", "created_by", "created_at", "updated_at")


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ("created_at", "item", "movement_type", "quantity_change", "quantity_after", "created_by")
    list_filter = ("movement_type",)
    search_fields = ("item__name", "item__variation__product__name", "reason")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Supplier)
class SupplierAdmin(NoDeleteMixin, admin.ModelAdmin):
    list_display = ("name", "contact_person", "phone", "email", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "contact_person", "email")


class PurchaseLineInline(admin.TabularInline):
    model = PurchaseLine
    extra = 0
    can_delete = False
    readonly_fields = ("item", "quantity", "unit", "unit_cost", "line_total")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Purchase)
class PurchaseAdmin(NoDeleteMixin, admin.ModelAdmin):
    """View only: create, edit and receive purchases in the inventory screens."""

    list_display = ("reference", "supplier", "purchase_date", "status", "total")
    list_filter = ("status",)
    search_fields = ("reference", "invoice_number", "supplier__name")
    inlines = [PurchaseLineInline]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
