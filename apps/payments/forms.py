from django import forms

from apps.accounts.forms import BootstrapFormMixin

from .services import validate_evidence


class BankTransferForm(BootstrapFormMixin, forms.Form):
    reference = forms.CharField(max_length=100, label="Transfer reference",
                                help_text="The reference or transaction number from your bank.")
    evidence = forms.FileField(label="Receipt or screenshot",
                               help_text="JPG, PNG, WebP or PDF, up to 5 MB.",
                               widget=forms.ClearableFileInput(attrs={"accept": "image/jpeg,image/png,image/webp,application/pdf"}))

    def clean_evidence(self):
        upload = self.cleaned_data["evidence"]
        validate_evidence(upload)
        return upload


class ReviewPaymentForm(forms.Form):
    decision = forms.ChoiceField(choices=[("approve", "Approve"), ("reject", "Reject")])
    note = forms.CharField(max_length=500, required=False)


class NoteForm(forms.Form):
    note = forms.CharField(max_length=500, required=False)
