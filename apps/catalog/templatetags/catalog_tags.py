from decimal import Decimal, InvalidOperation

from django import template
from django.conf import settings

register = template.Library()


@register.filter
def money(value):
    """Decimal -> "LKR 1,250.00". Empty values show an em dash."""
    if value in (None, ""):
        return "—"
    try:
        amount = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return "—"
    return f"{settings.CURRENCY_CODE} {amount:,.2f}"


@register.inclusion_tag("catalog/partials/_image.html")
def catalog_image(image, alt="", css_class=""):
    """Show an uploaded image, or the neutral placeholder if there is none."""
    return {"image": image, "alt": alt, "css_class": css_class}
