"""
Customer storefront and cart pages.

Browsing is public. Cart actions are POST-only (CSRF-protected), validate the
variation and quantity on the server, and only ever touch the visitor's own
cart (see services.get_cart). Staff accounts can browse but not shop.
"""
from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import TemplateView

from apps.catalog.models import Category, Product

from . import reviews, services
from .forms import AddToCartForm, ShopSearchForm, UpdateQuantityForm
from .models import CartItem, ProductReview


def _safe_next(request, fallback):
    target = request.POST.get("next") or request.GET.get("next")
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()},
                                                  require_https=request.is_secure()):
        return target
    return fallback


def _attach_card_options(products):
    """For product cards: the purchasable variations (for the quick-add selector)."""
    for product in products:
        product.card_options = [v for v in services.product_variations(product) if v.available > 0]
    return products


# ---------------------------------------------------------------------------
# Browsing
# ---------------------------------------------------------------------------
class ShopHomeView(TemplateView):
    """All products by category; switches to a results grid when searching or sorting."""

    template_name = "shop/index.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        form = ShopSearchForm(self.request.GET or None)
        q, sort = form.values()
        categories = services.visible_categories()
        ctx.update(form=form, categories=categories, sorts=services.SORTS, sort=sort, q=q)
        if q or "sort" in self.request.GET or "page" in self.request.GET:
            page = Paginator(services.search_products(q=q, sort=sort), settings.SHOP_PAGE_SIZE).get_page(self.request.GET.get("page"))
            _attach_card_options(page.object_list)
            ctx.update(mode="results", page_obj=page, querystring=_querystring(self.request))
        else:
            sections = []
            for main in categories:
                products = list(services.search_products(category=main)[:8])
                sections.append((main, _attach_card_options(products)))
            ctx.update(mode="sections", sections=sections)
        return ctx


class CategoryView(TemplateView):
    template_name = "shop/category.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        category = get_object_or_404(Category.objects.select_related("parent"), slug=self.kwargs["slug"], is_active=True)
        if category.parent_id and not category.parent.is_active:
            raise Http404
        form = ShopSearchForm(self.request.GET or None)
        q, sort = form.values()
        page = Paginator(services.search_products(q=q, category=category, sort=sort), settings.SHOP_PAGE_SIZE).get_page(self.request.GET.get("page"))
        _attach_card_options(page.object_list)
        main = category.parent or category
        categories = services.visible_categories()
        ctx.update(category=category, main=main, form=form, sorts=services.SORTS, sort=sort, q=q, page_obj=page,
                   querystring=_querystring(self.request), categories=categories,
                   subcategories=next((c.visible_subs for c in categories if c.pk == main.pk), []))
        return ctx


class ProductDetailView(TemplateView):
    template_name = "shop/product_detail.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        product = get_object_or_404(Product.objects.select_related("category", "subcategory"),
                                    slug=self.kwargs["slug"], status=Product.Status.ACTIVE, category__is_active=True)
        if product.subcategory_id and not product.subcategory.is_active:
            raise Http404
        variations = services.product_variations(product)
        for v in variations:
            v.availability = services.availability_label(v.available)
            v.max_qty = min(v.available, settings.CART_MAX_QUANTITY_PER_ITEM)
            v.is_low = 0 < v.available <= settings.SHOP_LOW_STOCK_THRESHOLD
        selectable = [v for v in variations if v.available > 0]
        requested = self.request.GET.get("option")
        selected = next((v for v in selectable if str(v.pk) == requested), selectable[0] if selectable else None)
        related = list(services.search_products(category=product.subcategory or product.category).exclude(pk=product.pk)[:4])
        ctx.update(product=product, variations=variations, selected=selected, can_shop=services.can_shop(self.request.user),
                   related=_attach_card_options(related))
        # Phase 09: wishlist and reviews
        user = self.request.user
        ctx.update(
            wishlisted=reviews.is_wishlisted(user, product), rating=reviews.rating_summary(product),
            reviews=product.reviews.filter(status=ProductReview.Status.APPROVED).select_related("customer")[:20],
            my_review=ProductReview.objects.filter(product=product, customer=user).first() if user.is_authenticated else None,
            can_review=reviews.has_bought(user, product),
        )
        return ctx


def _querystring(request):
    query = request.GET.copy()
    query.pop("page", None)
    return query.urlencode()


# ---------------------------------------------------------------------------
# Cart
# ---------------------------------------------------------------------------
class CartView(TemplateView):
    template_name = "shop/cart.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        cart = services.get_cart(self.request)
        summary = services.summarize_cart(cart)
        for note in summary.notes:
            messages.warning(self.request, note)
        ctx.update(summary=summary, can_shop=services.can_shop(self.request.user),
                   max_qty=settings.CART_MAX_QUANTITY_PER_ITEM)
        return ctx


class CartActionMixin(View):
    http_method_names = ["post"]

    def dispatch(self, request, *args, **kwargs):
        if not services.can_shop(request.user):
            messages.error(request, "Staff accounts can't use the shopping cart. Sign out and use a customer account to shop.")
            return redirect("shop:home")
        return super().dispatch(request, *args, **kwargs)

    def own_item(self, pk):
        """A cart line from the visitor's own cart, or 404 (never another person's line)."""
        cart = services.get_cart(self.request)
        if cart is None:
            raise Http404
        return get_object_or_404(CartItem.objects.select_related("variation__product"), pk=pk, cart=cart)


class AddToCartView(CartActionMixin):
    def post(self, request):
        form = AddToCartForm(request.POST)
        fallback = reverse("shop:cart")
        if not form.is_valid():
            messages.error(request, " ".join(e for errors in form.errors.values() for e in errors))
            return redirect(_safe_next(request, fallback))
        try:
            variation = services.purchasable_variation(form.cleaned_data["variation"])
            cart = services.get_cart(request, create=True)
            services.add_to_cart(cart, variation, form.cleaned_data["quantity"])
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
            return redirect(_safe_next(request, fallback))
        qty = form.cleaned_data["quantity"]
        messages.success(request, f"Added {qty} × {variation.product.name} ({variation.display_name}) to your cart.")
        return redirect(_safe_next(request, fallback))


class UpdateCartItemView(CartActionMixin):
    def post(self, request, pk):
        item = self.own_item(pk)
        form = UpdateQuantityForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Enter a quantity from 0 to %d." % settings.CART_MAX_QUANTITY_PER_ITEM)
            return redirect("shop:cart")
        try:
            result = services.set_quantity(item, form.cleaned_data["quantity"])
        except ValidationError as error:
            messages.error(request, f"{item.variation.product.name}: {' '.join(error.messages)}")
            return redirect("shop:cart")
        if result is None:
            messages.success(request, f"Removed {item.variation.product.name} from your cart.")
        else:
            messages.success(request, "Cart updated.")
        return redirect("shop:cart")


class RemoveCartItemView(CartActionMixin):
    def post(self, request, pk):
        item = self.own_item(pk)
        name = f"{item.variation.product.name} ({item.variation.display_name})"
        item.delete()
        messages.success(request, f"Removed {name} from your cart.")
        return redirect("shop:cart")
