"""Wishlist (customers), product reviews (customers who bought) and review moderation (Owner, Manager)."""
from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import TemplateView

from apps.accounts.forms import BootstrapFormMixin
from apps.accounts.permissions import CapabilityRequiredMixin, CustomerRequiredMixin
from apps.accounts.roles import Capability
from apps.catalog.models import Product

from . import reviews
from .models import ProductReview, WishlistItem


class ReviewForm(BootstrapFormMixin, forms.Form):
    rating = forms.TypedChoiceField(coerce=int, choices=[(5, "★★★★★ Excellent"), (4, "★★★★ Good"), (3, "★★★ Average"),
                                                         (2, "★★ Poor"), (1, "★ Very poor")])
    title = forms.CharField(max_length=100, label="Headline")
    body = forms.CharField(label="Your review", max_length=2000, widget=forms.Textarea(attrs={"rows": 5}))


def _visible_product(slug):
    return get_object_or_404(Product, slug=slug, status=Product.Status.ACTIVE, category__is_active=True)


class WishlistToggleView(CustomerRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request, slug):
        product = _visible_product(slug)
        added = reviews.toggle_wishlist(request.user, product)
        messages.success(request, f"{product.name} {'saved to' if added else 'removed from'} your wishlist.")
        target = request.POST.get("next", "")
        if not url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
            target = reverse("shop:product", args=[product.slug])
        return redirect(target)


class WishlistView(CustomerRequiredMixin, TemplateView):
    template_name = "shop/wishlist.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        items = (WishlistItem.objects.filter(user=self.request.user)
                 .select_related("product__category").order_by("-created_at"))
        ctx["items"] = items
        return ctx


class ReviewFormView(CustomerRequiredMixin, View):
    template_name = "shop/review_form.html"

    def setup_product(self, slug):
        product = _visible_product(slug)
        if not reviews.has_bought(self.request.user, product):
            messages.info(self.request, "You can review products after buying them.")
            return product, None
        return product, ProductReview.objects.filter(product=product, customer=self.request.user).first()

    def get(self, request, slug):
        product, review = self.setup_product(slug)
        if review is None and not reviews.has_bought(request.user, product):
            return redirect("shop:product", slug=slug)
        initial = {"rating": review.rating, "title": review.title, "body": review.body} if review else {"rating": 5}
        return render(request, self.template_name, {"product": product, "review": review, "form": ReviewForm(initial=initial)})

    def post(self, request, slug):
        product, review = self.setup_product(slug)
        form = ReviewForm(request.POST)
        if form.is_valid():
            try:
                review = reviews.save_review(request.user, product, form.cleaned_data["rating"], form.cleaned_data["title"],
                                             form.cleaned_data["body"])
            except ValidationError as error:
                form.add_error(None, " ".join(error.messages))
            else:
                messages.success(request, "Thank you! Your review will appear once we've checked it."
                                 if review.status == ProductReview.Status.PENDING else "Thank you! Your review is published.")
                return redirect("shop:product", slug=slug)
        return render(request, self.template_name, {"product": product, "review": review, "form": form})


class ReviewModerationView(CapabilityRequiredMixin, TemplateView):
    required_capability = Capability.MODERATE_REVIEWS
    template_name = "shop/review_moderation.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        status = self.request.GET.get("status", "PENDING")
        q = (self.request.GET.get("q") or "").strip()
        qs = ProductReview.objects.select_related("product", "customer", "moderated_by")
        if status in ProductReview.Status.values:
            qs = qs.filter(status=status)
        if q:
            qs = qs.filter(Q(product__name__icontains=q) | Q(title__icontains=q) | Q(body__icontains=q))
        rating = self.request.GET.get("rating")
        if rating in {"1", "2", "3", "4", "5"}:
            qs = qs.filter(rating=int(rating))
        query = self.request.GET.copy()
        query.pop("page", None)
        ctx.update(status=status, q=q, rating=rating or "", statuses=ProductReview.Status.choices,
                   querystring=query.urlencode(), page_obj=Paginator(qs, 20).get_page(self.request.GET.get("page")),
                   pending=ProductReview.objects.filter(status=ProductReview.Status.PENDING).count())
        return ctx


class ReviewModerateView(CapabilityRequiredMixin, View):
    required_capability = Capability.MODERATE_REVIEWS
    http_method_names = ["post"]

    def post(self, request, pk):
        review = get_object_or_404(ProductReview, pk=pk)
        approve = request.POST.get("decision") == "approve"
        try:
            reviews.moderate_review(review, request.user, approve, request.POST.get("note", ""))
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        else:
            messages.success(request, "Review published." if approve else "Review not published; the customer was told why.")
        return redirect(request.POST.get("back") if url_has_allowed_host_and_scheme(
            request.POST.get("back", ""), allowed_hosts={request.get_host()}) else "shop:review_moderation")
