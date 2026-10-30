from django.contrib import messages
from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

from .models import Cart
from .services import SESSION_CART_KEY, merge_guest_cart


@receiver(user_logged_in)
def keep_guest_cart_on_sign_in(sender, request, user, **kwargs):
    """
    A guest who signs in (or registers) keeps what they put in the cart: the
    guest cart is merged into their customer cart. Staff accounts don't have
    carts, so a guest cart is simply left behind (and cleaned up later).
    """
    if request is None or not hasattr(request, "session"):
        return
    cart_id = request.session.pop(SESSION_CART_KEY, None)
    if not cart_id or not getattr(user, "is_customer", False):
        return
    guest = Cart.objects.filter(pk=cart_id, user__isnull=True).first()
    if guest is None or not guest.items.exists():
        if guest:
            guest.delete()
        return
    _, notes = merge_guest_cart(guest, user)
    if hasattr(request, "_messages"):
        messages.info(request, "We kept the items you added to your cart before signing in.")
        for note in notes:
            messages.warning(request, note)
