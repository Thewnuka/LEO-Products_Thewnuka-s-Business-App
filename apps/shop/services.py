"""
Storefront and cart logic.

What customers can see and buy
------------------------------
A variation is *purchasable* when:
  - its product is ACTIVE, its main category is active and (if set) its
    subcategory is active;
  - the variation is active;
  - it has an active inventory record (Phase 04) with at least 1 in stock.
A product is listed in the shop when it is visible (active, in active categories)
and has at least one active variation. Products with nothing in stock are still
listed so customers can see the full range, but they are marked "Out of stock"
and cannot be added to the cart.
Stock always comes from the inventory module; the cart never changes it.
"""
from dataclasses import dataclass, field
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Case, Count, IntegerField, Min, Q, Value, When
from django.db.models.functions import Coalesce

from apps.catalog.models import Category, Product, ProductVariation

from .models import Cart, CartItem

SESSION_CART_KEY = "shop_cart_id"


# Conditions on a ProductVariation (prefix "") or through Product.variations (prefix "variations__").
def _variation_available(prefix=""):
    return Q(**{
        f"{prefix}is_active": True,
        f"{prefix}inventory_item__is_active": True,
        f"{prefix}inventory_item__quantity__gte": 1,
    })


def _product_visible(prefix=""):
    return (Q(**{f"{prefix}status": Product.Status.ACTIVE, f"{prefix}category__is_active": True})
            & (Q(**{f"{prefix}subcategory__isnull": True}) | Q(**{f"{prefix}subcategory__is_active": True})))


# ---------------------------------------------------------------------------
# Storefront queries
# ---------------------------------------------------------------------------
def visible_products():
    """
    Active products (in active categories) with at least one active variation.
    `available_count` = purchasable variations (0 = out of stock); `from_price` =
    the lowest price a customer can buy now, or the lowest listed price when out of stock.
    """
    listed = Q(variations__is_active=True)
    available = _variation_available("variations__")
    return (Product.objects.filter(_product_visible())
            .annotate(option_count=Count("variations", filter=listed, distinct=True),
                      available_count=Count("variations", filter=available, distinct=True),
                      from_price=Coalesce(Min("variations__selling_price", filter=available),
                                          Min("variations__selling_price", filter=listed)))
            .filter(option_count__gt=0)
            .select_related("category", "subcategory"))


# Quick "variety" filters shown on a main category's pages (main category name -> search words).
# They search product names and descriptions, so new products appear under them automatically.
VARIETY_FILTERS = {
    "LEO TEA": ["Black", "Ginger", "Cinnamon"],
}


def variety_filters(main_category):
    return VARIETY_FILTERS.get(main_category.name.upper(), [])


def visible_categories():
    """
    Active main categories that have products listed, each with all of its active
    subcategories (e.g. LEO TEA: Tea Bags and Tea Packets), so the structure is always clear.
    """
    main_ids = set(visible_products().values_list("category_id", flat=True))
    mains = list(Category.objects.main().filter(is_active=True, pk__in=main_ids))
    subs = Category.objects.sub().filter(is_active=True, parent_id__in=main_ids)
    by_parent = {}
    for sub in subs:
        by_parent.setdefault(sub.parent_id, []).append(sub)
    for main in mains:
        main.visible_subs = by_parent.get(main.pk, [])
    return mains


SORTS = {
    "relevant": "Most relevant",
    "newest": "Newest",
    "price_asc": "Price: low to high",
    "price_desc": "Price: high to low",
    "name": "Name (A–Z)",
}


def search_products(q="", category=None, sort="relevant"):
    qs = visible_products()
    if category is not None:
        qs = qs.filter(subcategory=category) if category.parent_id else qs.filter(category=category)
    q = (q or "").strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(description__icontains=q) | Q(category__name__icontains=q)
                       | Q(subcategory__name__icontains=q))
    if sort == "newest":
        return qs.order_by("-created_at", "-pk")  # ties (same timestamp): newest record first
    if sort == "price_asc":
        return qs.order_by("from_price", "name")
    if sort == "price_desc":
        return qs.order_by("-from_price", "name")
    if sort == "name":
        return qs.order_by("name")
    if q:  # relevance: name starts with the term > name contains it > anything else
        qs = qs.annotate(rank=Case(When(name__istartswith=q, then=Value(0)), When(name__icontains=q, then=Value(1)),
                                   default=Value(2), output_field=IntegerField()))
        return qs.order_by("rank", "name")
    return qs.order_by("category__sort_order", "subcategory__sort_order", "name")


def product_variations(product):
    """All active variations of a product, each with `available` (whole units in stock, 0 if not purchasable)."""
    visible = Product.objects.filter(pk=product.pk).filter(_product_visible()).exists()
    variations = list(product.variations.filter(is_active=True)
                      .select_related("unit", "inventory_item").order_by("sort_order", "measurement_type", "quantity"))
    for v in variations:
        v.available = available_stock(v) if visible else 0
    return variations


def available_stock(variation):
    """Whole units a customer may put in the cart now (0 when not purchasable)."""
    product = variation.product
    if not (variation.is_active and product.status == Product.Status.ACTIVE and product.category.is_active
            and (product.subcategory_id is None or product.subcategory.is_active)):
        return 0
    item = getattr(variation, "inventory_item", None)
    if item is None or not item.is_active or item.quantity < 1:
        return 0
    return int(item.quantity)  # finished goods are whole packets


def availability_label(available):
    if available <= 0:
        return "Out of stock"
    if available <= settings.SHOP_LOW_STOCK_THRESHOLD:
        return f"Only {available} left"
    return "In stock"


def purchasable_variation(variation_id):
    """Look up a variation a customer may buy, or raise ValidationError."""
    try:
        variation_id = int(variation_id)
    except (TypeError, ValueError):
        raise ValidationError("Please choose a product option.")
    variation = (ProductVariation.objects.select_related("product__category", "product__subcategory", "unit", "inventory_item")
                 .filter(pk=variation_id).first())
    if variation is None or available_stock(variation) <= 0:
        raise ValidationError("Sorry, this item is not available right now.")
    return variation


# ---------------------------------------------------------------------------
# Cart ownership
# ---------------------------------------------------------------------------
def can_shop(user):
    """Guests and customers have carts; staff accounts browse only."""
    return not user.is_authenticated or user.is_customer


def get_cart(request, create=False):
    """
    The current visitor's cart (or None). Customers: their own cart. Guests:
    the cart id stored in their server-side session, and only if it is a guest
    cart. Nobody can reach a cart by changing a URL.
    """
    user = request.user
    if user.is_authenticated:
        if not user.is_customer:
            return None
        cart = Cart.objects.filter(user=user).first()
        if cart is None and create:
            cart, _ = Cart.objects.get_or_create(user=user)
        return cart
    cart_id = request.session.get(SESSION_CART_KEY)
    cart = Cart.objects.filter(pk=cart_id, user__isnull=True).first() if cart_id else None
    if cart is None and create:
        cart = Cart.objects.create()
        request.session[SESSION_CART_KEY] = cart.pk
    return cart


def get_cart_for_user(user):
    """A customer's own cart (created if missing). Used at checkout, where only signed-in customers buy."""
    cart, _ = Cart.objects.get_or_create(user=user)
    return cart


def cart_count(request):
    cart = get_cart(request)
    if cart is None:
        return 0
    return sum(cart.items.values_list("quantity", flat=True))


# ---------------------------------------------------------------------------
# Cart changes (always validated against current stock)
# ---------------------------------------------------------------------------
def _limit(variation):
    return min(available_stock(variation), settings.CART_MAX_QUANTITY_PER_ITEM)


@transaction.atomic
def add_to_cart(cart, variation, quantity):
    """Add `quantity` of a purchasable variation. Returns the CartItem. Raises ValidationError."""
    quantity = _whole_quantity(quantity)
    item = CartItem.objects.select_for_update().filter(cart=cart, variation=variation).first()
    current = item.quantity if item else 0
    limit = _limit(variation)
    if current + quantity > limit:
        if limit <= 0:
            raise ValidationError("Sorry, this item is out of stock.")
        already = f" You already have {current} in your cart." if current else ""
        raise ValidationError(f"Only {limit} available.{already}")
    if item:
        item.quantity = current + quantity
        item.save(update_fields=["quantity", "updated_at"])
    else:
        item = CartItem.objects.create(cart=cart, variation=variation, quantity=quantity)
    Cart.objects.filter(pk=cart.pk).update(updated_at=item.updated_at)
    return item


@transaction.atomic
def set_quantity(item, quantity):
    """Change a line's quantity (0 removes it). Raises ValidationError if stock is insufficient."""
    quantity = _whole_quantity(quantity, allow_zero=True)
    if quantity == 0:
        item.delete()
        return None
    variation = ProductVariation.objects.select_related("product__category", "product__subcategory", "inventory_item").get(pk=item.variation_id)
    limit = _limit(variation)
    if quantity > limit:
        raise ValidationError("Sorry, this item is out of stock." if limit <= 0 else f"Only {limit} available.")
    item.quantity = quantity
    item.save(update_fields=["quantity", "updated_at"])
    return item


def _whole_quantity(value, allow_zero=False):
    try:
        number = Decimal(str(value))
    except Exception:
        raise ValidationError("Enter a whole number.")
    if number != number.to_integral_value():
        raise ValidationError("Enter a whole number.")
    number = int(number)
    if number < (0 if allow_zero else 1):
        raise ValidationError("Quantity must be at least 1.")
    if number > settings.CART_MAX_QUANTITY_PER_ITEM:
        raise ValidationError(f"You can order up to {settings.CART_MAX_QUANTITY_PER_ITEM} of one item online.")
    return number


@transaction.atomic
def merge_guest_cart(guest_cart, user):
    """Move a guest's cart into the customer's cart when they sign in (capped at available stock)."""
    target, _ = Cart.objects.get_or_create(user=user)
    notes = []
    for line in guest_cart.items.select_related("variation__product__category", "variation__product__subcategory",
                                                "variation__inventory_item", "variation__unit"):
        existing = target.items.filter(variation=line.variation).first()
        wanted = line.quantity + (existing.quantity if existing else 0)
        allowed = min(wanted, _limit(line.variation))
        if allowed <= 0:
            notes.append(f"{line.variation.product.name} ({line.variation.display_name}) is no longer available.")
            continue
        if allowed < wanted:
            notes.append(f"{line.variation.product.name} ({line.variation.display_name}) was limited to {allowed} (stock).")
        if existing:
            existing.quantity = allowed
            existing.save(update_fields=["quantity", "updated_at"])
        else:
            CartItem.objects.create(cart=target, variation=line.variation, quantity=allowed)
    guest_cart.delete()
    return target, notes


# ---------------------------------------------------------------------------
# Cart page summary
# ---------------------------------------------------------------------------
@dataclass
class CartLine:
    item: CartItem
    available: int
    unit_price: Decimal
    status: str = "ok"          # ok | reduced | unavailable
    note: str = ""

    @property
    def line_total(self):
        return self.unit_price * self.item.quantity if self.status != "unavailable" else Decimal("0.00")


@dataclass
class CartSummary:
    lines: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    @property
    def item_count(self):
        return sum(line.item.quantity for line in self.lines if line.status != "unavailable")

    @property
    def subtotal(self):
        return sum((line.line_total for line in self.lines), Decimal("0.00"))

    @property
    def total(self):
        return self.subtotal  # delivery and other charges are added at checkout (Phase 06)


def summarize_cart(cart):
    """
    Build the cart page, re-checking every line against current stock. If
    stock fell since the item was added, the quantity is reduced to what is
    available (and the customer is told); unavailable items are flagged and
    excluded from the total.
    """
    summary = CartSummary()
    if cart is None:
        return summary
    items = cart.items.select_related("variation__product__category", "variation__product__subcategory",
                                      "variation__inventory_item", "variation__unit")
    for item in items:
        variation = item.variation
        available = _limit(variation)
        line = CartLine(item=item, available=available, unit_price=variation.selling_price)
        name = f"{variation.product.name} ({variation.display_name})"
        if available <= 0:
            line.status, line.note = "unavailable", "No longer available. Remove it from your cart."
        elif item.quantity > available:
            item.quantity = available
            item.save(update_fields=["quantity", "updated_at"])
            line.status, line.note = "reduced", f"Only {available} available; quantity reduced."
            summary.notes.append(f"{name}: only {available} available, so the quantity was reduced.")
        summary.lines.append(line)
    return summary
