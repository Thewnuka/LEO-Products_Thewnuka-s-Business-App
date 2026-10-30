from django import forms

from apps.accounts.forms import BootstrapFormMixin
from apps.accounts.models import phone_validator

from .models import CheckoutSettings, DeliveryZone, Order
from .services import fulfilment_options, payment_options

F = Order.Fulfilment
PM = Order.PaymentMethod


class CheckoutForm(BootstrapFormMixin, forms.Form):
    """Contact, delivery and payment choices. Prices and totals are never taken from the browser."""

    full_name = forms.CharField(max_length=150, widget=forms.TextInput(attrs={"autocomplete": "name"}))
    phone = forms.CharField(max_length=20, label="Contact number", validators=[phone_validator],
                            widget=forms.TextInput(attrs={"autocomplete": "tel", "inputmode": "tel"}))
    fulfilment = forms.ChoiceField(label="How would you like to receive your order?", widget=forms.RadioSelect)
    delivery_zone = forms.ModelChoiceField(DeliveryZone.objects.none(), required=False, label="Delivery area",
                                           empty_label="Choose your delivery area")
    address_line1 = forms.CharField(max_length=200, required=False, label="Address",
                                    widget=forms.TextInput(attrs={"autocomplete": "address-line1", "placeholder": "House number and street"}))
    address_line2 = forms.CharField(max_length=200, required=False, label="Address line 2 (optional)",
                                    widget=forms.TextInput(attrs={"autocomplete": "address-line2"}))
    city = forms.CharField(max_length=100, required=False, label="Town / city",
                           widget=forms.TextInput(attrs={"autocomplete": "address-level2"}))
    delivery_instructions = forms.CharField(max_length=500, required=False, label="Delivery instructions (optional)",
                                            widget=forms.Textarea(attrs={"rows": 2, "placeholder": "e.g. landmark, best time to call"}))
    payment_method = forms.ChoiceField(label="Payment method", widget=forms.RadioSelect)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.config = CheckoutSettings.load()
        fulfilments = fulfilment_options(self.config)
        self.fields["fulfilment"].choices = [(f.value, f.label) for f in F if f in fulfilments]
        self.fields["delivery_zone"].queryset = DeliveryZone.objects.filter(is_active=True)
        self.fields["delivery_zone"].label_from_instance = lambda z: f"{z.name} – LKR {z.fee:,.2f}" + (
            f" (free over LKR {z.free_delivery_over:,.0f})" if z.free_delivery_over is not None else "")
        methods = set()
        for f in fulfilments:
            methods.update(payment_options(f, self.config))
        self.fields["payment_method"].choices = [(m.value, m.label) for m in PM if m in methods]
        for name in ("fulfilment", "payment_method"):
            self.fields[name].widget.attrs["class"] = "form-check-input"
        if len(fulfilments) == 1:
            self.fields["fulfilment"].initial = fulfilments[0]

    def clean(self):
        cleaned = super().clean()
        fulfilment, method = cleaned.get("fulfilment"), cleaned.get("payment_method")
        if fulfilment == F.DELIVERY:
            for name, message in (("delivery_zone", "Choose your delivery area."), ("address_line1", "Enter your address."),
                                  ("city", "Enter your town or city.")):
                if not cleaned.get(name):
                    self.add_error(name, message)
        elif fulfilment == F.PICKUP:
            for name in ("delivery_zone", "address_line1", "address_line2", "city"):
                cleaned[name] = None if name == "delivery_zone" else ""
        if fulfilment and method and method not in payment_options(fulfilment, self.config):
            self.add_error("payment_method", "This payment method isn't available for the option you chose.")
        return cleaned


class CancelOrderForm(BootstrapFormMixin, forms.Form):
    reason = forms.CharField(max_length=500, widget=forms.Textarea(attrs={"rows": 2}), label="Reason for cancelling")


class StatusChangeForm(forms.Form):
    to_status = forms.ChoiceField(choices=Order.Status.choices)
    note = forms.CharField(max_length=500, required=False)


class OrderFilterForm(BootstrapFormMixin, forms.Form):
    q = forms.CharField(required=False, label="Search",
                        widget=forms.TextInput(attrs={"type": "search", "placeholder": "Order no., name, phone or email"}))
    status = forms.ChoiceField(required=False, choices=[("", "Any status"), ("OPEN", "All open orders")] + list(Order.Status.choices))
    payment_method = forms.ChoiceField(required=False, label="Payment method", choices=[("", "Any method")] + list(PM.choices))
    payment_status = forms.ChoiceField(required=False, label="Payment status",
                                       choices=[("", "Any payment status")] + list(Order.PaymentStatus.choices))
    date_from = forms.DateField(required=False, label="From", widget=forms.DateInput(attrs={"type": "date"}))
    date_to = forms.DateField(required=False, label="To", widget=forms.DateInput(attrs={"type": "date"}))


class CheckoutSettingsForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = CheckoutSettings
        fields = ["delivery_enabled", "pickup_enabled", "pickup_address", "pickup_hours",
                  "cash_on_delivery_enabled", "cash_on_pickup_enabled", "bank_transfer_enabled",
                  "bank_name", "bank_branch", "bank_account_name", "bank_account_number", "bank_instructions"]
        widgets = {"pickup_address": forms.Textarea(attrs={"rows": 2}), "bank_instructions": forms.Textarea(attrs={"rows": 2})}

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("bank_transfer_enabled") and not all(cleaned.get(f) for f in ("bank_name", "bank_account_name", "bank_account_number")):
            self.add_error("bank_transfer_enabled", "Fill in the bank name, account name and account number to accept bank transfers.")
        if not cleaned.get("delivery_enabled") and not cleaned.get("pickup_enabled"):
            self.add_error("pickup_enabled", "Offer at least delivery or pickup, otherwise customers can't check out.")
        return cleaned


class DeliveryZoneForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = DeliveryZone
        fields = ["name", "areas", "fee", "free_delivery_over", "sort_order", "is_active"]
        widgets = {"areas": forms.Textarea(attrs={"rows": 2}),
                   "fee": forms.NumberInput(attrs={"step": "0.01", "min": "0", "inputmode": "decimal"}),
                   "free_delivery_over": forms.NumberInput(attrs={"step": "0.01", "min": "0", "inputmode": "decimal"})}
        labels = {"fee": "Delivery fee (LKR)", "free_delivery_over": "Free delivery over (LKR, optional)", "is_active": "Active"}
