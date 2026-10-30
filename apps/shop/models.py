"""
Shopping cart.

  Cart        one per signed-in customer (user), or one per guest browser session
              (user empty; found only through the server-side session, never by URL)
  CartItem    a product variation and a quantity (whole packets)

A cart never reserves or reduces stock: inventory is reduced when an order
is placed (Phase 06). Prices are not stored here; the cart always shows the
variation's current selling price.
"""
from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

from apps.catalog.models import ProductVariation
from apps.core.models import TimeStampedModel


class Cart(TimeStampedModel):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE,
                                related_name="cart", help_text="Empty for a guest cart.")

    def __str__(self):
        return f"Cart of {self.user}" if self.user_id else f"Guest cart #{self.pk}"

    @property
    def is_guest(self):
        return self.user_id is None


class CartItem(TimeStampedModel):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name="items")
    variation = models.ForeignKey(ProductVariation, on_delete=models.CASCADE, related_name="cart_items")
    quantity = models.PositiveIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(settings.CART_MAX_QUANTITY_PER_ITEM)])

    class Meta(TimeStampedModel.Meta):
        ordering = ["created_at", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["cart", "variation"], name="shop_cartitem_one_line_per_variation"),
            models.CheckConstraint(condition=Q(quantity__gte=1), name="shop_cartitem_quantity_positive"),
        ]

    def __str__(self):
        return f"{self.quantity} × {self.variation}"
