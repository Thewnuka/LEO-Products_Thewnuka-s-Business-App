"""
Catalogue management pages (staff portal).

Every view requires Capability.MANAGE_CATALOG (OWNER and MANAGER).
Nothing is hard-deleted except empty categories; products, variations and
units are archived by deactivating them.
"""
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, ProtectedError
from django.shortcuts import get_object_or_404, redirect
from django.views import View
from django.views.generic import CreateView, DetailView, TemplateView, UpdateView

from apps.accounts.permissions import CapabilityRequiredMixin
from apps.accounts.roles import Capability

from .forms import CategoryForm, ProductFilterForm, ProductForm, ProductStatusForm, UnitForm, VariationForm
from .models import Category, MeasurementType, Product, ProductVariation, Unit
from .services import catalog_stats, filter_products


class CatalogAccessMixin(CapabilityRequiredMixin):
    required_capability = Capability.MANAGE_CATALOG


def querystring_without_page(request):
    query = request.GET.copy()
    query.pop("page", None)
    return query.urlencode()


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
class CatalogDashboardView(CatalogAccessMixin, TemplateView):
    template_name = "catalog/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["stats"] = catalog_stats()
        ctx["recent_products"] = (
            Product.objects.select_related("category", "subcategory").with_variation_summary().order_by("-updated_at")[:6]
        )
        ctx["main_categories"] = Category.objects.main().annotate(
            product_count=Count("main_products", distinct=True), sub_count=Count("children", distinct=True)
        )
        return ctx


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------
class ProductListView(CatalogAccessMixin, TemplateView):
    template_name = "catalog/product_list.html"
    paginate_by = 12

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        form = ProductFilterForm(self.request.GET or None)
        products = filter_products(form.filters())
        page = Paginator(products, self.paginate_by).get_page(self.request.GET.get("page"))
        view_mode = "table" if self.request.GET.get("view") == "table" else "cards"
        query = self.request.GET.copy()
        query.pop("page", None)
        query.pop("view", None)
        ctx.update(
            filter_form=form,
            page_obj=page,
            querystring=querystring_without_page(self.request),
            filter_querystring=query.urlencode(),
            view_mode=view_mode,
            active_filter_count=sum(1 for k in ("q", "category", "subcategory", "status", "measurement") if self.request.GET.get(k)),
        )
        return ctx


class ProductCreateView(CatalogAccessMixin, CreateView):
    model = Product
    form_class = ProductForm
    template_name = "catalog/product_form.html"

    def form_valid(self, form):
        form.instance.created_by = form.instance.updated_by = self.request.user
        product = form.save()
        messages.success(self.request, f"“{product.name}” created. Now add its sizes and prices.")
        return redirect("catalog:variation_create", product_pk=product.pk)


class ProductUpdateView(CatalogAccessMixin, UpdateView):
    model = Product
    form_class = ProductForm
    template_name = "catalog/product_form.html"
    context_object_name = "product"

    def form_valid(self, form):
        form.instance.updated_by = self.request.user
        product = form.save()
        messages.success(self.request, f"“{product.name}” saved.")
        return redirect(product)


class ProductDetailView(CatalogAccessMixin, DetailView):
    template_name = "catalog/product_detail.html"
    context_object_name = "product"

    def get_queryset(self):
        return Product.objects.select_related("category", "subcategory", "created_by", "updated_by").with_variation_summary()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["variations"] = self.object.variations.select_related("unit").order_by("sort_order", "measurement_type", "quantity")
        ctx["status_choices"] = Product.Status.choices
        return ctx


class ProductStatusView(CatalogAccessMixin, View):
    http_method_names = ["post"]

    def post(self, request, pk):
        product = get_object_or_404(Product, pk=pk)
        form = ProductStatusForm(request.POST)
        if form.is_valid():
            product.status = form.cleaned_data["status"]
            try:
                product.full_clean(exclude=["image"])
            except ValidationError as error:
                messages.error(request, " ".join(error.messages))
            else:
                product.updated_by = request.user
                product.save(update_fields=["status", "updated_by", "updated_at"])
                messages.success(request, f"“{product.name}” is now {product.get_status_display().lower()}.")
        return redirect(product)


# ---------------------------------------------------------------------------
# Variations
# ---------------------------------------------------------------------------
class ProductScopedMixin(CatalogAccessMixin):
    """Views under /products/<product_pk>/variations/."""

    def get_product(self):
        if not hasattr(self, "_product"):
            self._product = get_object_or_404(Product.objects.select_related("category"), pk=self.kwargs["product_pk"])
        return self._product

    def get_context_data(self, **kwargs):
        return super().get_context_data(product=self.get_product(), **kwargs)


class VariationListView(ProductScopedMixin, TemplateView):
    template_name = "catalog/variation_list.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["variations"] = self.get_product().variations.select_related("unit").order_by("sort_order", "measurement_type", "quantity")
        return ctx


class VariationFormMixin(ProductScopedMixin):
    model = ProductVariation
    form_class = VariationForm
    template_name = "catalog/variation_form.html"

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "product": self.get_product()}

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["measurement_types"] = MeasurementType.choices
        return ctx


class VariationCreateView(VariationFormMixin, CreateView):
    def get_initial(self):
        last = self.get_product().variations.select_related("unit").order_by("-created_at").first()
        return {"measurement_type": last.measurement_type, "unit": last.unit_id} if last else {}

    def form_valid(self, form):
        form.instance.created_by = form.instance.updated_by = self.request.user
        variation = form.save()
        messages.success(self.request, f"Variation {variation.display_name} added with SKU {variation.sku}.")
        if "save_and_add" in self.request.POST:
            return redirect("catalog:variation_create", product_pk=self.get_product().pk)
        return redirect("catalog:variation_list", product_pk=self.get_product().pk)


class VariationUpdateView(VariationFormMixin, UpdateView):
    context_object_name = "variation"

    def get_queryset(self):
        return ProductVariation.objects.filter(product=self.get_product())

    def form_valid(self, form):
        form.instance.updated_by = self.request.user
        variation = form.save()
        messages.success(self.request, f"Variation {variation.display_name} saved.")
        return redirect("catalog:variation_list", product_pk=self.get_product().pk)


class VariationToggleView(ProductScopedMixin, View):
    http_method_names = ["post"]

    def post(self, request, product_pk, pk):
        product = self.get_product()
        variation = get_object_or_404(ProductVariation, pk=pk, product=product)
        if variation.is_active and product.status == Product.Status.ACTIVE \
                and not product.variations.filter(is_active=True).exclude(pk=variation.pk).exists():
            messages.error(request, "This is the product's last active variation. Deactivate the product first, or add another variation.")
            return redirect("catalog:variation_list", product_pk=product.pk)
        variation.is_active = not variation.is_active
        variation.updated_by = request.user
        variation.save(update_fields=["is_active", "updated_by", "updated_at"])
        state = "activated" if variation.is_active else "deactivated"
        messages.success(request, f"Variation {variation.display_name} {state}.")
        return redirect("catalog:variation_list", product_pk=product.pk)


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------
class CategoryListView(CatalogAccessMixin, TemplateView):
    template_name = "catalog/category_list.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        children = Category.objects.sub().annotate(product_count=Count("sub_products", distinct=True))
        mains = list(Category.objects.main().annotate(product_count=Count("main_products", distinct=True)))
        by_parent = {}
        for child in children:
            by_parent.setdefault(child.parent_id, []).append(child)
        for main in mains:
            main.subs = by_parent.get(main.pk, [])
        ctx["main_categories"] = mains
        return ctx


class CategoryCreateView(CatalogAccessMixin, CreateView):
    model = Category
    form_class = CategoryForm
    template_name = "catalog/category_form.html"

    def get_initial(self):
        parent = self.request.GET.get("parent")
        return {"parent": parent} if parent and parent.isdigit() else {}

    def form_valid(self, form):
        category = form.save()
        kind = "Subcategory" if category.parent_id else "Main category"
        messages.success(self.request, f"{kind} “{category.name}” created.")
        return redirect("catalog:category_list")


class CategoryUpdateView(CatalogAccessMixin, UpdateView):
    model = Category
    form_class = CategoryForm
    template_name = "catalog/category_form.html"
    context_object_name = "category"

    def form_valid(self, form):
        category = form.save()
        messages.success(self.request, f"“{category.name}” saved.")
        return redirect("catalog:category_list")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        obj = self.object
        ctx["can_delete"] = not (obj.children.exists() or obj.main_products.exists() or obj.sub_products.exists())
        return ctx


class CategoryToggleView(CatalogAccessMixin, View):
    http_method_names = ["post"]

    def post(self, request, pk):
        category = get_object_or_404(Category, pk=pk)
        category.is_active = not category.is_active
        category.save(update_fields=["is_active", "updated_at"])
        messages.success(request, f"“{category.name}” {'activated' if category.is_active else 'deactivated'}.")
        return redirect("catalog:category_list")


class CategoryDeleteView(CatalogAccessMixin, View):
    """Only empty categories (no subcategories, no products) can be deleted."""

    http_method_names = ["post"]

    def post(self, request, pk):
        category = get_object_or_404(Category, pk=pk)
        name = category.name
        try:
            category.delete()
        except ProtectedError:
            messages.error(request, f"“{name}” still has subcategories or products, so it cannot be deleted. Deactivate it instead.")
            return redirect("catalog:category_update", pk=pk)
        messages.success(request, f"“{name}” deleted.")
        return redirect("catalog:category_list")


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------
class UnitListView(CatalogAccessMixin, TemplateView):
    template_name = "catalog/unit_list.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        units = Unit.objects.annotate(variation_count=Count("variations"))
        ctx["groups"] = [
            (label, [u for u in units if u.measurement_type == value]) for value, label in MeasurementType.choices
        ]
        return ctx


class UnitCreateView(CatalogAccessMixin, CreateView):
    model = Unit
    form_class = UnitForm
    template_name = "catalog/unit_form.html"

    def form_valid(self, form):
        unit = form.save()
        messages.success(self.request, f"Unit “{unit.symbol}” added.")
        return redirect("catalog:unit_list")


class UnitUpdateView(CatalogAccessMixin, UpdateView):
    model = Unit
    form_class = UnitForm
    template_name = "catalog/unit_form.html"
    context_object_name = "unit"

    def form_valid(self, form):
        unit = form.save()
        messages.success(self.request, f"Unit “{unit.symbol}” saved.")
        return redirect("catalog:unit_list")


class UnitToggleView(CatalogAccessMixin, View):
    http_method_names = ["post"]

    def post(self, request, pk):
        unit = get_object_or_404(Unit, pk=pk)
        unit.is_active = not unit.is_active
        unit.save(update_fields=["is_active", "updated_at"])
        messages.success(request, f"Unit “{unit.symbol}” {'activated' if unit.is_active else 'deactivated'}. Existing variations keep it.")
        return redirect("catalog:unit_list")
