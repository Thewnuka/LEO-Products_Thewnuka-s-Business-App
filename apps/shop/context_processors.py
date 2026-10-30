from .services import can_shop, cart_count


def cart(request):
    """Cart badge in the navbar. Never creates a cart; staff accounts have none."""
    user = getattr(request, "user", None)
    if user is None or not hasattr(request, "session"):
        return {"show_cart": False, "cart_count": 0}
    shop = can_shop(user)
    return {"show_cart": shop, "cart_count": cart_count(request) if shop else 0}
