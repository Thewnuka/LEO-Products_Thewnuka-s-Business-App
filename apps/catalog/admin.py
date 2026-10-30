from django.contrib import admin

from .models import Category, Product, ProductVariation, Unit


class NoDeleteMixin:
    """Archive (deactivate) instead of deleting from the admin site."""

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("__str__", "is_active", "sort_order", "updated_at")
    list_filter = ("is_active", "parent")
    search_fields = ("name",)
    readonly_fields = ("slug", "created_at", "updated_at")


@admin.register(Unit)
class UnitAdmin(NoDeleteMixin, admin.ModelAdmin):
    list_display = ("symbol", "name", "measurement_type", "attach_symbol", "is_active")
    list_filter = ("measurement_type", "is_active")


class VariationInline(admin.TabularInline):
    model = ProductVariation
    extra = 0
    fields = ("measurement_type", "quantity", "unit", "name", "sku", "selling_price", "wholesale_price", "is_active")
    can_delete = False


@admin.register(Product)
class ProductAdmin(NoDeleteMixin, admin.ModelAdmin):
    list_display = ("name", "category", "subcategory", "status", "updated_at")
    list_filter = ("status", "category")
    search_fields = ("name", "variations__sku")
    readonly_fields = ("created_by", "updated_by", "created_at", "updated_at")
    inlines = [VariationInline]


@admin.register(ProductVariation)
class ProductVariationAdmin(NoDeleteMixin, admin.ModelAdmin):
    list_display = ("sku", "product", "size_label", "selling_price", "wholesale_price", "is_active")
    list_filter = ("measurement_type", "is_active")
    search_fields = ("sku", "product__name")
    readonly_fields = ("created_by", "updated_by", "created_at", "updated_at")
