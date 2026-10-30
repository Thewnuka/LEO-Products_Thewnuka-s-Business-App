from decimal import Decimal

from django import forms

from apps.accounts.forms import BootstrapFormMixin
from apps.accounts.models import User
from apps.accounts.roles import Capability, has_capability
from apps.orders.models import Order

from .models import CashierShift, CashMovement, PosSettings

MONEY_WIDGET = {"step": "0.01", "min": "0", "inputmode": "decimal"}


def money_field(label, **kwargs):
    return forms.DecimalField(label=label, max_digits=12, decimal_places=2, min_value=Decimal("0"),
                              widget=forms.NumberInput(attrs=MONEY_WIDGET), **kwargs)


class OpenShiftForm(BootstrapFormMixin, forms.Form):
    opening_cash = money_field("Opening cash in the drawer (LKR)")
    opening_note = forms.CharField(label="Note (optional)", max_length=200, required=False)


class CashMovementForm(BootstrapFormMixin, forms.Form):
    kind = forms.ChoiceField(label="Type", choices=[(CashMovement.Kind.CASH_IN.value, "Cash in (added to the drawer)"),
                                                    (CashMovement.Kind.CASH_OUT.value, "Cash out (taken from the drawer)")])
    amount = forms.DecimalField(label="Amount (LKR)", max_digits=12, decimal_places=2, min_value=Decimal("0.01"),
                                widget=forms.NumberInput(attrs=MONEY_WIDGET))
    reason = forms.CharField(max_length=200, widget=forms.TextInput(attrs={"placeholder": "e.g. change float, bank deposit"}))


class CloseShiftForm(BootstrapFormMixin, forms.Form):
    counted_cash = money_field("Cash counted in the drawer (LKR)")
    closing_note = forms.CharField(label="Note", required=False, widget=forms.Textarea(attrs={"rows": 2}),
                                   help_text="Required if the count is different from the expected cash.")


class RefundForm(BootstrapFormMixin, forms.Form):
    reason = forms.CharField(label="Reason", max_length=300)
    drawer = forms.ModelChoiceField(label="Pay the cash refund from", required=False, queryset=CashierShift.objects.none(),
                                    empty_label="Choose an open till")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["drawer"].queryset = CashierShift.objects.filter(status=CashierShift.Status.OPEN).select_related("cashier")
        self.fields["drawer"].label_from_instance = lambda s: f"{s.code} · {s.cashier.get_full_name() or s.cashier.username}"


class SalesFilterForm(BootstrapFormMixin, forms.Form):
    q = forms.CharField(label="Receipt number", required=False,
                        widget=forms.TextInput(attrs={"type": "search", "placeholder": "e.g. POS-2026-00012"}))
    date_from = forms.DateField(label="From", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    date_to = forms.DateField(label="To", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    cashier = forms.ModelChoiceField(label="Cashier", required=False, queryset=User.objects.none(), empty_label="All cashiers")
    payment_method = forms.ChoiceField(label="Payment", required=False,
                                       choices=[("", "Any payment"), (Order.PaymentMethod.CASH.value, "Cash"),
                                                (Order.PaymentMethod.BANK_TRANSFER.value, "Bank transfer")])
    status = forms.ChoiceField(label="Status", required=False,
                               choices=[("", "Any status"), ("COMPLETED", "Completed"), ("PENDING", "Awaiting transfer check"),
                                        ("CANCELLED", "Voided / refunded")])

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None and has_capability(user, Capability.VIEW_POS_SALES):
            self.fields["cashier"].queryset = User.objects.filter(pos_sales__isnull=False).distinct().order_by("username")
        else:
            del self.fields["cashier"]


class PosSettingsForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = PosSettings
        fields = ["business_address", "business_phone", "receipt_footer", "cashier_discount_limit", "manager_discount_limit"]
        widgets = {"business_address": forms.Textarea(attrs={"rows": 2})}

    def clean(self):
        cleaned = super().clean()
        cashier, manager = cleaned.get("cashier_discount_limit"), cleaned.get("manager_discount_limit")
        if cashier is not None and manager is not None and cashier > manager:
            self.add_error("cashier_discount_limit", "The cashier limit can't be higher than the manager limit.")
        return cleaned
