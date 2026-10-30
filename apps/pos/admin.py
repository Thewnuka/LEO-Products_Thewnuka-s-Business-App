from django.contrib import admin

from .models import CashierShift, CashMovement, PosSettings, ReceiptPrint


class ReadOnlyAdmin(admin.ModelAdmin):
    """POS records are changed only through the POS screens (audit trail)."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class CashMovementInline(admin.TabularInline):
    model = CashMovement
    extra = 0
    can_delete = False
    readonly_fields = ["kind", "amount", "reason", "order", "created_by", "created_at"]

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(CashierShift)
class CashierShiftAdmin(ReadOnlyAdmin):
    list_display = ["code", "cashier", "status", "opened_at", "closed_at", "opening_cash", "expected_cash",
                    "counted_cash", "difference"]
    list_filter = ["status"]
    inlines = [CashMovementInline]


@admin.register(ReceiptPrint)
class ReceiptPrintAdmin(ReadOnlyAdmin):
    list_display = ["order", "printed_by", "printed_at"]


@admin.register(PosSettings)
class PosSettingsAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return not PosSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
