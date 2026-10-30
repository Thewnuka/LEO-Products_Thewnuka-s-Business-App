"""
Inventory, supplier and purchase pages (staff portal).

Stock is changed ONLY through services.record_movement / receive_purchase.
Capabilities: inventory pages MANAGE_INVENTORY, suppliers MANAGE_SUPPLIERS,
purchases MANAGE_PURCHASES (Owner and Manager). Negative-stock permission is
an Owner-only setting (CONFIGURE_STOCK_RULES).
"""
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, DetailView, TemplateView, UpdateView

from apps.accounts.permissions import CapabilityRequiredMixin
from apps.accounts.roles import Capability

from . import services
from .forms import (
    CancelPurchaseForm,
    InventoryItemForm,
    ItemFilterForm,
    MovementFilterForm,
    PurchaseFilterForm,
    PurchaseForm,
    PurchaseLineFormSet,
    StockAdjustmentForm,
    SupplierFilterForm,
    SupplierForm,
)
from .models import InventoryItem, Purchase, StockMovement, Supplier


class InventoryAccess(CapabilityRequiredMixin):
    required_capability = Capability.MANAGE_INVENTORY


class SupplierAccess(CapabilityRequiredMixin):
    required_capability = Capability.MANAGE_SUPPLIERS


class PurchaseAccess(CapabilityRequiredMixin):
    required_capability = Capability.MANAGE_PURCHASES


def paginate(request, queryset, per_page=20):
    page = Paginator(queryset, per_page).get_page(request.GET.get("page"))
    query = request.GET.copy()
    query.pop("page", None)
    return page, query.urlencode()


def movement_rows():
    return StockMovement.objects.select_related(
        "item__stock_unit", "item__variation__product", "item__variation__unit", "entered_unit", "created_by", "purchase")


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
class InventoryDashboardView(InventoryAccess, TemplateView):
    template_name = "inventory/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["stats"] = services.inventory_stats()
        ctx["alerts"] = (InventoryItem.objects.needs_attention().with_stock_status()
                         .select_related("stock_unit", "variation__product", "variation__unit").order_by("quantity")[:10])
        ctx["recent_movements"] = movement_rows()[:8]
        ctx["recent_purchases"] = Purchase.objects.select_related("supplier")[:5]
        return ctx


# ---------------------------------------------------------------------------
# Inventory items
# ---------------------------------------------------------------------------
class ItemListView(InventoryAccess, TemplateView):
    template_name = "inventory/item_list.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        form = ItemFilterForm(self.request.GET or None)
        page, querystring = paginate(self.request, services.filter_items(form.filters()))
        ctx.update(filter_form=form, page_obj=page, querystring=querystring,
                   active_filter_count=sum(1 for k in ("q", "state", "kind", "category", "unit", "active") if self.request.GET.get(k)))
        return ctx


class ItemCreateView(InventoryAccess, CreateView):
    model = InventoryItem
    form_class = InventoryItemForm
    template_name = "inventory/item_form.html"

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "user": self.request.user}

    def get_initial(self):
        initial = {"kind": InventoryItem.Kind.RAW_MATERIAL}
        if self.request.GET.get("variation", "").isdigit():
            initial.update(kind=InventoryItem.Kind.FINISHED_GOOD, variation=self.request.GET["variation"])
        return initial

    def form_valid(self, form):
        try:
            item = services.create_item_with_opening_stock(form.save(commit=False), form.cleaned_data.get("opening_quantity"),
                                                           self.request.user)
        except ValidationError as error:
            form.add_error(None, error)
            return self.form_invalid(form)
        messages.success(self.request, f"Now tracking stock for “{item.display_name}”: {item.quantity_display}.")
        return redirect(item)


class ItemUpdateView(InventoryAccess, UpdateView):
    model = InventoryItem
    form_class = InventoryItemForm
    template_name = "inventory/item_form.html"
    context_object_name = "item"

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "user": self.request.user}

    def form_valid(self, form):
        item = form.save()
        messages.success(self.request, f"Settings for “{item.display_name}” saved. Stock quantity is unchanged.")
        return redirect(item)


class ItemDetailView(InventoryAccess, DetailView):
    template_name = "inventory/item_detail.html"
    context_object_name = "item"

    def get_queryset(self):
        return InventoryItem.objects.select_related("stock_unit", "category", "variation__product__category",
                                                    "variation__product__subcategory", "variation__unit", "created_by")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["movements"] = movement_rows().filter(item=self.object)[:25]
        ctx["purchase_lines"] = (self.object.purchase_lines.select_related("purchase__supplier", "unit")
                                 .order_by("-purchase__purchase_date")[:10])
        return ctx


class StockAdjustView(InventoryAccess, View):
    """
    Step 1 (POST without "confirm"): validate and show a confirmation page.
    Step 2 (POST with "confirm"): apply the change through the service.
    """

    template_name = "inventory/adjust.html"

    def get_item(self):
        return get_object_or_404(InventoryItem.objects.select_related("stock_unit", "variation__product", "variation__unit"),
                                 pk=self.kwargs["pk"])

    def get(self, request, pk):
        item = self.get_item()
        initial = {"movement_type": request.GET.get("type")} if request.GET.get("type") else {}
        return render(request, self.template_name, {"item": item, "form": StockAdjustmentForm(item=item, initial=initial)})

    def post(self, request, pk):
        item = self.get_item()
        form = StockAdjustmentForm(request.POST, item=item)
        if not form.is_valid():
            return render(request, self.template_name, {"item": item, "form": form})
        d = form.cleaned_data
        if "edit" in request.POST:  # "Back to edit" on the confirmation page
            return render(request, self.template_name, {"item": item, "form": form})
        if "confirm" not in request.POST:
            preview = services.preview_movement(item, d["movement_type"], d["quantity"], d.get("unit"), d.get("direction"))
            return render(request, self.template_name, {"item": item, "form": form, "preview": preview,
                                                        "movement_label": StockMovement.Type(d["movement_type"]).label})
        try:
            movement = services.record_movement(item, d["movement_type"], d["quantity"], request.user,
                                                reason=d["reason"], unit=d.get("unit"), direction=d.get("direction"))
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
            return render(request, self.template_name, {"item": item, "form": form})
        messages.success(request, f"{movement.get_movement_type_display()} recorded. "
                                  f"Stock is now {item.format_qty(movement.quantity_after)}.")
        return redirect(item)


class MovementListView(InventoryAccess, TemplateView):
    """The stock ledger: read-only, newest first."""

    template_name = "inventory/movement_list.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        form = MovementFilterForm(self.request.GET or None)
        rows = movement_rows()
        if form.is_bound and form.is_valid():
            d = form.cleaned_data
            if d["q"]:
                rows = rows.filter(Q(item__name__icontains=d["q"]) | Q(item__variation__product__name__icontains=d["q"])
                                   | Q(item__variation__sku__icontains=d["q"]))
            if d["movement_type"]:
                rows = rows.filter(movement_type=d["movement_type"])
            if d["date_from"]:
                rows = rows.filter(created_at__date__gte=d["date_from"])
            if d["date_to"]:
                rows = rows.filter(created_at__date__lte=d["date_to"])
        page, querystring = paginate(self.request, rows, 25)
        ctx.update(filter_form=form, page_obj=page, querystring=querystring)
        return ctx


# ---------------------------------------------------------------------------
# Suppliers
# ---------------------------------------------------------------------------
class SupplierListView(SupplierAccess, TemplateView):
    template_name = "inventory/supplier_list.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        form = SupplierFilterForm(self.request.GET or None)
        rows = Supplier.objects.annotate(
            purchase_count=Count("purchases", filter=Q(purchases__status=Purchase.Status.RECEIVED)))
        if form.is_bound and form.is_valid():
            q = form.cleaned_data["q"].strip()
            if q:
                rows = rows.filter(Q(name__icontains=q) | Q(contact_person__icontains=q) | Q(phone__icontains=q) | Q(email__icontains=q))
            if form.cleaned_data["active"]:
                rows = rows.filter(is_active=form.cleaned_data["active"] == "yes")
        page, querystring = paginate(self.request, rows.order_by("name"))
        ctx.update(filter_form=form, page_obj=page, querystring=querystring)
        return ctx


class SupplierCreateView(SupplierAccess, CreateView):
    model = Supplier
    form_class = SupplierForm
    template_name = "inventory/supplier_form.html"

    def form_valid(self, form):
        supplier = form.save()
        messages.success(self.request, f"Supplier “{supplier.name}” added.")
        return redirect(supplier)


class SupplierUpdateView(SupplierAccess, UpdateView):
    model = Supplier
    form_class = SupplierForm
    template_name = "inventory/supplier_form.html"
    context_object_name = "supplier"

    def form_valid(self, form):
        supplier = form.save()
        messages.success(self.request, f"Supplier “{supplier.name}” saved.")
        return redirect(supplier)


class SupplierDetailView(SupplierAccess, DetailView):
    model = Supplier
    template_name = "inventory/supplier_detail.html"
    context_object_name = "supplier"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        purchases = self.object.purchases.annotate(line_count=Count("lines")).order_by("-purchase_date", "-pk")
        ctx["page_obj"], ctx["querystring"] = paginate(self.request, purchases, 15)
        ctx["received_total"] = purchases.filter(status=Purchase.Status.RECEIVED).aggregate(t=Sum("total"))["t"]
        return ctx


class SupplierToggleView(SupplierAccess, View):
    http_method_names = ["post"]

    def post(self, request, pk):
        supplier = get_object_or_404(Supplier, pk=pk)
        supplier.is_active = not supplier.is_active
        supplier.save(update_fields=["is_active", "updated_at"])
        messages.success(request, f"“{supplier.name}” {'activated' if supplier.is_active else 'deactivated'}.")
        return redirect(supplier)


# ---------------------------------------------------------------------------
# Purchases
# ---------------------------------------------------------------------------
class PurchaseListView(PurchaseAccess, TemplateView):
    template_name = "inventory/purchase_list.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        form = PurchaseFilterForm(self.request.GET or None)
        page, querystring = paginate(self.request, services.filter_purchases(form.filters()))
        ctx.update(filter_form=form, page_obj=page, querystring=querystring)
        return ctx


class PurchaseFormMixin(PurchaseAccess):
    template_name = "inventory/purchase_form.html"

    def render_forms(self, form, formset, purchase=None):
        return render(self.request, self.template_name, {"form": form, "formset": formset, "purchase": purchase})

    def save(self, form, formset, creating):
        with transaction.atomic():
            purchase = form.save(commit=False)
            if creating:
                services.save_new_purchase(purchase, self.request.user)
            else:
                purchase.save()
            formset.instance = purchase
            formset.save()
            purchase.recalculate_totals()
        return purchase


class PurchaseCreateView(PurchaseFormMixin, View):
    def get(self, request):
        form = PurchaseForm(initial={"purchase_date": timezone.localdate(), "supplier": request.GET.get("supplier")})
        return self.render_forms(form, PurchaseLineFormSet(prefix="lines"))

    def post(self, request):
        form = PurchaseForm(request.POST)
        formset = PurchaseLineFormSet(request.POST, prefix="lines", instance=Purchase())
        if not (form.is_valid() and formset.is_valid()):
            return self.render_forms(form, formset)
        purchase = self.save(form, formset, creating=True)
        messages.success(request, f"Draft purchase {purchase.reference} saved. Stock changes only when you receive it.")
        return redirect(purchase)


class PurchaseUpdateView(PurchaseFormMixin, View):
    def get_purchase(self):
        purchase = get_object_or_404(Purchase, pk=self.kwargs["pk"])
        if not purchase.is_editable:
            messages.error(self.request, f"{purchase.reference} is {purchase.get_status_display().lower()} and can no longer be edited.")
            return None, redirect(purchase)
        return purchase, None

    def get(self, request, pk):
        purchase, refusal = self.get_purchase()
        if refusal:
            return refusal
        return self.render_forms(PurchaseForm(instance=purchase), PurchaseLineFormSet(instance=purchase, prefix="lines"), purchase)

    def post(self, request, pk):
        purchase, refusal = self.get_purchase()
        if refusal:
            return refusal
        form = PurchaseForm(request.POST, instance=purchase)
        formset = PurchaseLineFormSet(request.POST, instance=purchase, prefix="lines")
        if not (form.is_valid() and formset.is_valid()):
            return self.render_forms(form, formset, purchase)
        with transaction.atomic():
            # Re-check under lock: it may have been received in another tab meanwhile.
            if not Purchase.objects.select_for_update().filter(pk=purchase.pk, status=Purchase.Status.DRAFT).exists():
                messages.error(request, "This purchase was received or cancelled meanwhile; your changes were not saved.")
                return redirect(purchase)
            purchase = self.save(form, formset, creating=False)
        messages.success(request, f"Draft {purchase.reference} saved.")
        return redirect(purchase)


class PurchaseDetailView(PurchaseAccess, DetailView):
    template_name = "inventory/purchase_detail.html"
    context_object_name = "purchase"

    def get_queryset(self):
        return Purchase.objects.select_related("supplier", "created_by", "received_by", "cancelled_by")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["lines"] = self.object.lines.select_related("item__stock_unit", "item__variation__product", "item__variation__unit",
                                                        "unit", "movement")
        ctx["cancel_form"] = CancelPurchaseForm()
        return ctx


class PurchaseReceiveView(PurchaseAccess, View):
    """GET: confirmation page listing what will be added. POST: receive (once only)."""

    def get(self, request, pk):
        purchase = get_object_or_404(Purchase.objects.select_related("supplier"), pk=pk)
        if not purchase.is_editable:
            messages.info(request, f"{purchase.reference} is already {purchase.get_status_display().lower()}.")
            return redirect(purchase)
        lines = purchase.lines.select_related("item__stock_unit", "item__variation__product", "item__variation__unit", "unit")
        rows = []
        for line in lines:
            try:
                add = line.stock_quantity()
                rows.append({"line": line, "add": add, "after": line.item.quantity + add, "error": None})
            except ValidationError as error:
                rows.append({"line": line, "add": None, "after": None, "error": " ".join(error.messages)})
        return render(request, "inventory/purchase_receive.html", {"purchase": purchase, "rows": rows,
                                                                   "has_errors": any(r["error"] for r in rows)})

    def post(self, request, pk):
        purchase = get_object_or_404(Purchase, pk=pk)
        try:
            services.receive_purchase(purchase, request.user)
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
            return redirect(purchase)
        messages.success(request, f"{purchase.reference} received. Stock has been updated for {purchase.lines.count()} item(s).")
        return redirect(purchase)


class PurchaseCancelView(PurchaseAccess, View):
    http_method_names = ["post"]

    def post(self, request, pk):
        purchase = get_object_or_404(Purchase, pk=pk)
        form = CancelPurchaseForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Please give a reason for cancelling.")
            return redirect(purchase)
        try:
            services.cancel_purchase(purchase, request.user, form.cleaned_data["reason"])
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        else:
            messages.success(request, f"{purchase.reference} cancelled. Stock was not changed.")
        return redirect(purchase)
