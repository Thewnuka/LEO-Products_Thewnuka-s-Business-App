"""Forms for the Owner's home page image manager (see hero.py for the saving logic)."""
from django import forms

from apps.accounts.forms import BootstrapFormMixin

from .models import HomeHeroImage, HomeHeroSettings

IMAGE_ACCEPT = "image/jpeg,image/png,image/webp"
IMAGE_HELP = "JPG, PNG or WebP, up to 5 MB. Large photos are resized automatically."


def _image_field(required, label):
    return forms.FileField(
        required=required, label=label, help_text=IMAGE_HELP,
        widget=forms.FileInput(attrs={"accept": IMAGE_ACCEPT}),
    )


class HeroBackgroundForm(BootstrapFormMixin, forms.Form):
    image = _image_field(False, "New background photo")
    focus = forms.ChoiceField(label="Keep this part of the photo in view", choices=HomeHeroSettings.Focus.choices)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["image"].help_text = IMAGE_HELP + " A wide (landscape) photo with a calm, dark area on the left works best."


class HeroImageAddForm(BootstrapFormMixin, forms.Form):
    box = forms.TypedChoiceField(choices=HomeHeroImage.Box.choices, coerce=int, widget=forms.HiddenInput)
    image = _image_field(True, "Photo")
    alt_text = forms.CharField(label="Short description", max_length=150,
                               help_text="Describes the photo for screen readers, e.g. \"Kokis on a white plate\".")


class HeroImageEditForm(BootstrapFormMixin, forms.Form):
    image = _image_field(False, "Replace photo")
    alt_text = forms.CharField(label="Short description", max_length=150)
    sort_order = forms.IntegerField(label="Position", min_value=0, max_value=999,
                                    help_text="Lower numbers are shown first.")
