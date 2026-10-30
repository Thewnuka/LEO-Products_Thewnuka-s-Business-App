"""Read-only payment records. Payments change only through the staff order screens (services.py)."""
from django.contrib import admin

from .models import Payment, PaymentEvent


class PaymentEventInline(admin.TabularInline):
    model = PaymentEvent
    extra = 0
    can_delete = False
    fields = readonly_fields = ("created_at", "event", "detail", "created_by")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("reference", "order", "method", "amount", "status", "created_at")
    list_filter = ("method", "status")
    search_fields = ("reference", "order__number", "bank_reference", "transaction_id")
    exclude = ("evidence",)  # slips are viewed through the permission-checked staff page
    inlines = [PaymentEventInline]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
