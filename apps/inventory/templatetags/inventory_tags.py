from django import template

register = template.Library()


@register.filter
def qty(value, item):
    """{{ value|qty:item }} -> "20 kg" / "35 packets" in the item's own unit."""
    return item.format_qty(value)


@register.filter
def qty_signed(value, item):
    """{{ movement.quantity_change|qty_signed:item }} -> "+5 packets" / "−250 g"."""
    if value is None:
        return "—"
    sign = "+" if value > 0 else "−" if value < 0 else ""
    return f"{sign}{item.format_qty(abs(value))}"
