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


# ---------------------------------------------------------------------------
# Wishlist and reviews (Phase 09)
# ---------------------------------------------------------------------------
class WishlistItem(models.Model):
    """A product a customer saved for later (one row per customer and product)."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="wishlist_items")
    product = models.ForeignKey("catalog.Product", on_delete=models.CASCADE, related_name="wishlisted_by")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [models.UniqueConstraint(fields=["user", "product"], name="shop_wishlist_one_per_product")]

    def __str__(self):
        return f"{self.user} ♥ {self.product}"


class ProductReview(TimeStampedModel):
    """
    A rating and comment by a customer who bought the product (paid, not cancelled).
    One per customer and product; editing it sends it back for approval when approval is required.
    """

    class Status(models.TextChoices):
        PENDING = "PENDING", "Waiting for approval"
        APPROVED = "APPROVED", "Published"
        REJECTED = "REJECTED", "Not published"

    product = models.ForeignKey("catalog.Product", on_delete=models.CASCADE, related_name="reviews")
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="product_reviews")
    rating = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    title = models.CharField(max_length=100)
    body = models.TextField("review", max_length=2000)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.PENDING, db_index=True)
    submitted_at = models.DateTimeField(editable=False)
    moderated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                     related_name="+", editable=False)
    moderated_at = models.DateTimeField(null=True, blank=True, editable=False)
    moderation_note = models.CharField(max_length=300, blank=True, help_text="Shown to the customer if not published.")

    class Meta(TimeStampedModel.Meta):
        ordering = ["-submitted_at", "-pk"]
        constraints = [
            models.UniqueConstraint(fields=["product", "customer"], name="shop_review_one_per_customer"),
            models.CheckConstraint(condition=Q(rating__gte=1) & Q(rating__lte=5), name="shop_review_rating_1_to_5"),
        ]

    def __str__(self):
        return f"{self.product}: {self.rating}★ by {self.customer}"

    @property
    def display_name(self):
        """Public name: first name and initial only (never the email)."""
        first, last = self.customer.first_name.strip(), self.customer.last_name.strip()
        if not first:
            return "LEO PRODUCTS customer"
        return f"{first} {last[:1]}." if last else first
