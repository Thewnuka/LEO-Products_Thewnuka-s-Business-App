"""Catalogue business logic: slugs, SKUs, product search and statistics."""
import re

from django.db.models import Q
from django.utils.text import slugify

from .models import Category, Product, ProductVariation, format_decimal

# ---------------------------------------------------------------------------
# Slugs
# ---------------------------------------------------------------------------
def unique_slug(model, text, exclude_pk=None, max_length=90):
    base = slugify(text)[:max_length].strip("-") or "item"
    slug, n = base, 2
    qs = model.objects.all()
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    while qs.filter(slug=slug).exists():
        slug = f"{base}-{n}"
        n += 1
    return slug


# ---------------------------------------------------------------------------
# SKUs
# ---------------------------------------------------------------------------
def category_code(category):
    """Initials of the main category name: "LEO TEA" -> "LT", "TEA BAGS" -> "TB"."""
    words = re.findall(r"[A-Za-z0-9]+", category.name if category else "")
    code = "".join(w[0] for w in words).upper()
    return (code or "GEN")[:4]


def suggest_sku(product, quantity, unit):
    """
    LEO-<category initials>-<product number>-<size>, e.g. LEO-LT-0007-200G,
    LEO-TB-0012-25BAGS, LEO-LS-0003-10PIECES.
    """
    size = format_decimal(quantity).replace(".", "P") + re.sub(r"[^A-Za-z0-9]", "", unit.symbol)
    return f"LEO-{category_code(product.category)}-{product.pk:04d}-{size}".upper()[:40]


def generate_sku(variation):
    base = suggest_sku(variation.product, variation.quantity, variation.unit)
    sku, n = base, 2
    while ProductVariation.objects.filter(sku__iexact=sku).exclude(pk=variation.pk).exists():
        suffix = f"-{n}"
        sku = base[: 40 - len(suffix)] + suffix
        n += 1
    return sku


# ---------------------------------------------------------------------------
# Product search, filters and sorting
# ---------------------------------------------------------------------------
PRODUCT_SORTS = {
    "name": ("name", "Name (A–Z)"),
    "-name": ("-name", "Name (Z–A)"),
    "-updated": ("-updated_at", "Recently updated"),
    "-created": ("-created_at", "Newest first"),
    "created": ("created_at", "Oldest first"),
    "price": ("min_price", "Lowest price"),
    "-price": ("-max_price", "Highest price"),
}
DEFAULT_SORT = "name"


def filter_products(params, queryset=None):
    """
    Apply search and filters from a dict-like `params` (e.g. request.GET):
    q (name or SKU), category, subcategory, status, measurement, sort.
    """
    qs = (queryset if queryset is not None else Product.objects.all())
    qs = qs.select_related("category", "subcategory").with_variation_summary()

    q = (params.get("q") or "").strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(variations__sku__icontains=q)).distinct()
    if params.get("category"):
        qs = qs.filter(category_id=params["category"])
    if params.get("subcategory"):
        qs = qs.filter(subcategory_id=params["subcategory"])
    if params.get("status"):
        qs = qs.filter(status=params["status"])
    if params.get("measurement"):
        qs = qs.filter(variations__measurement_type=params["measurement"]).distinct()

    sort_key = params.get("sort") if params.get("sort") in PRODUCT_SORTS else DEFAULT_SORT
    field = PRODUCT_SORTS[sort_key][0]
    if field.lstrip("-") in ("min_price", "max_price"):
        from django.db.models import F

        expr = F(field.lstrip("-"))
        qs = qs.order_by(expr.desc(nulls_last=True) if field.startswith("-") else expr.asc(nulls_last=True), "name")
    else:
        qs = qs.order_by(field, "-pk" if field.startswith("-") else "pk")  # ties follow the sort direction
    return qs


# ---------------------------------------------------------------------------
# Dashboard statistics (always from the database)
# ---------------------------------------------------------------------------
def catalog_stats():
    products = Product.objects.all()
    return {
        "total_products": products.count(),
        "active_products": products.filter(status=Product.Status.ACTIVE).count(),
        "inactive_products": products.filter(status=Product.Status.INACTIVE).count(),
        "draft_products": products.filter(status=Product.Status.DRAFT).count(),
        "main_categories": Category.objects.main().count(),
        "subcategories": Category.objects.sub().count(),
        "total_variations": ProductVariation.objects.count(),
        "active_variations": ProductVariation.objects.active().count(),
    }
