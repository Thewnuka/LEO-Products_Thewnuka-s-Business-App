import uuid
from decimal import Decimal

from django import forms
from django.utils import timezone

from apps.accounts.forms import BootstrapFormMixin
from apps.inventory.models import Purchase, Supplier
from apps.payments.services import validate_evidence

from .models import ExpenseCategory, PaymentMethod
from .services import PRESETS

MONEY_ATTRS = {"step": "0.01", "min": "0.01", "inputmode": "decimal"}


class TokenMixin(forms.Form):
    """A hidden one-time token: resubmitting the same form returns the record already created."""

    token = forms.UUIDField(widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("initial", {}).setdefault("token", uuid.uuid4())
        super().__init__(*args, **kwargs)


class ExpenseForm(BootstrapFormMixin, TokenMixin):
    expense_date = forms.DateField(label="Date", widget=forms.DateInput(attrs={"type": "date"}))
    category = forms.ModelChoiceField(queryset=ExpenseCategory.objects.filter(is_active=True), empty_label="Choose a category")
    amount = forms.DecimalField(label="Amount (LKR)", max_digits=14, decimal_places=2, min_value=Decimal("0.01"),
                                widget=forms.NumberInput(attrs=MONEY_ATTRS))
    payment_method = forms.ChoiceField(label="Paid by", choices=PaymentMethod.choices)
    description = forms.CharField(max_length=300, widget=forms.TextInput(attrs={"placeholder": "e.g. Electricity bill, March"}))
    paid_to = forms.CharField(label="Paid to (optional)", max_length=150, required=False)
    payment_reference = forms.CharField(label="Bill / reference number (optional)", max_length=100, required=False)
    receipt = forms.FileField(label="Receipt (optional)", required=False, help_text="JPG, PNG, WebP or PDF, up to 5 MB.",
                              widget=forms.ClearableFileInput(attrs={"accept": "image/jpeg,image/png,image/webp,application/pdf"}))

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("initial", {}).setdefault("expense_date", timezone.localdate())
        super().__init__(*args, **kwargs)

    def clean_expense_date(self):
        value = self.cleaned_data["expense_date"]
        if value > timezone.localdate():
            raise forms.ValidationError("The date can't be in the future.")
        return value

    def clean_receipt(self):
        upload = self.cleaned_data.get("receipt")
        if upload:
            validate_evidence(upload)
        return upload


class SupplierPaymentForm(BootstrapFormMixin, TokenMixin):
    supplier = forms.ModelChoiceField(queryset=Supplier.objects.order_by("name"), empty_label="Choose a supplier")
    purchase = forms.ModelChoiceField(label="For purchase (optional)", required=False,
                                      queryset=Purchase.objects.none(), empty_label="General payment on account")
    payment_date = forms.DateField(label="Date", widget=forms.DateInput(attrs={"type": "date"}))
    amount = forms.DecimalField(label="Amount (LKR)", max_digits=14, decimal_places=2, min_value=Decimal("0.01"),
                                widget=forms.NumberInput(attrs=MONEY_ATTRS))
    payment_method = forms.ChoiceField(label="Paid by", choices=PaymentMethod.choices)
    payment_reference = forms.CharField(label="Reference (optional)", max_length=100, required=False)
    notes = forms.CharField(label="Notes (optional)", max_length=300, required=False)

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("initial", {}).setdefault("payment_date", timezone.localdate())
        super().__init__(*args, **kwargs)
        self.fields["purchase"].queryset = (Purchase.objects.filter(status=Purchase.Status.RECEIVED)
                                            .select_related("supplier").order_by("-purchase_date", "-pk"))
        self.fields["purchase"].label_from_instance = (
            lambda p: f"{p.reference} · {p.supplier.name} · {p.purchase_date:%d %b %Y} · LKR {p.total:,.2f}")

    def clean(self):
        cleaned = super().clean()
        purchase, supplier = cleaned.get("purchase"), cleaned.get("supplier")
        if purchase and supplier and purchase.supplier_id != supplier.pk:
            self.add_error("purchase", "This purchase is from another supplier.")
        return cleaned


class VoidForm(BootstrapFormMixin, forms.Form):
    reason = forms.CharField(max_length=300, label="Reason for voiding")


class ExpenseCategoryForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = ExpenseCategory
        fields = ["name", "description", "is_active"]


class ItemCostForm(BootstrapFormMixin, forms.Form):
    cost = forms.DecimalField(label="Cost per stock unit (LKR)", max_digits=14, decimal_places=4, min_value=Decimal("0"),
                              widget=forms.NumberInput(attrs={"step": "0.0001", "min": "0", "inputmode": "decimal"}))
    reason = forms.CharField(max_length=200, label="Where does this cost come from?",
                             widget=forms.TextInput(attrs={"placeholder": "e.g. production cost sheet, March 2026"}))


class PeriodForm(BootstrapFormMixin, forms.Form):
    """Date filter shared by the dashboard, reports and lists (read with services.period_from)."""

    period = forms.ChoiceField(choices=PRESETS, required=False)
    start = forms.DateField(label="From", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    end = forms.DateField(label="To", required=False, widget=forms.DateInput(attrs={"type": "date"}))


class ExpenseFilterForm(PeriodForm):
    category = forms.ModelChoiceField(queryset=ExpenseCategory.objects.all(), required=False, empty_label="All categories")
    payment_method = forms.ChoiceField(label="Paid by", required=False, choices=[("", "Any method")] + PaymentMethod.choices)
    status = forms.ChoiceField(required=False, choices=[("", "Recorded"), ("VOID", "Void"), ("ALL", "All")])

