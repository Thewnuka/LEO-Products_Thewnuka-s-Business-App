"""
Point-of-sale pages (staff portal, /staff/pos/).

Cashier (and Owner):  till screen, own shift (open, cash in/out, close), own sales and receipts.
Manager and Owner:    every sale and shift, discount approval, refunds (voids), shift review.
Owner:                POS settings (receipt details, discount limits).

Every rule is enforced here and in services.py; templates only hide what a user can't do.
"""
import json
import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate
from django.contrib.auth.mixins import AccessMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Count
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView, UpdateView

from apps.accounts import throttling
from apps.accounts.permissions import STAFF_LOGIN_URL, CapabilityRequiredMixin
from apps.accounts.roles import Capability, has_capability
from apps.orders.models import Order
from apps.payments.models import Payment

from . import services
from .forms import CashMovementForm, CloseShiftForm, OpenShiftForm, PosSettingsForm, RefundForm, SalesFilterForm
from .models import CashierShift, PosSettings


def _errors(error):
    return " ".join(error.messages) if isinstance(error, ValidationError) else str(error)


class AnyCapabilityMixin(AccessMixin):
    """Allow users with ANY of `capabilities` (finer checks happen per object)."""

    capabilities = ()
    login_url = STAFF_LOGIN_URL

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not any(has_capability(request.user, c) for c in self.capabilities):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


SALES_VIEWERS = (Capability.VIEW_POS_SALES, Capability.VIEW_OWN_TRANSACTIONS)
SHIFT_VIEWERS = (Capability.MANAGE_SHIFTS, Capability.PROCESS_SALES)


def get_sale(user, number):
    order = get_object_or_404(Order, number=number, channel=Order.Channel.POS)
    if not services.can_view_sale(user, order):
        raise Http404  # don't reveal other cashiers' sales
    return order


def get_shift(user, pk):
    return get_object_or_404(services.visible_shifts(user).select_related("cashier", "closed_by"), pk=pk)


# ---------------------------------------------------------------------------
# Till
# ---------------------------------------------------------------------------
class TerminalView(CapabilityRequiredMixin, View):
    required_capability = Capability.PROCESS_SALES

    def get(self, request):
        shift = services.current_shift(request.user)
        if shift is None:
            return render(request, "pos/open_shift.html", {"form": OpenShiftForm()})
        config = PosSettings.load()
        products = []
        categories = {}
        for v in services.sellable_variations():
            category = v.product.category
            categories[category.pk] = category.name
            products.append({
                "id": v.pk, "product": v.product.name, "size": v.display_name, "sku": v.sku,
                "price": str(v.selling_price), "stock": services.shop.available_stock(v), "category": category.pk,
            })
        return render(request, "pos/terminal.html", {
            "shift": shift, "summary": services.shift_summary(shift), "config": config,
            "pos_data": {
                "products": products,
                "categories": [{"id": pk, "name": name} for pk, name in sorted(categories.items(), key=lambda c: c[1])],
                "token": str(uuid.uuid4()),
                "discountLimit": str(services.discount_limit(request.user, config)),
                "checkoutUrl": reverse("pos:checkout"),
                "currency": settings.CURRENCY_CODE,
            },
        })


class OpenShiftView(CapabilityRequiredMixin, View):
    required_capability = Capability.PROCESS_SALES
    http_method_names = ["post"]

    def post(self, request):
        form = OpenShiftForm(request.POST)
        if not form.is_valid():
            return render(request, "pos/open_shift.html", {"form": form})
        try:
            shift = services.open_shift(request.user, form.cleaned_data["opening_cash"], form.cleaned_data["opening_note"])
        except ValidationError as error:
            messages.error(request, _errors(error))
        else:
            messages.success(request, f"Shift {shift.code} opened with LKR {shift.opening_cash:,.2f} in the drawer.")
        return redirect("pos:terminal")


class CheckoutView(CapabilityRequiredMixin, View):
    """JSON endpoint used by the till screen. Totals are always recalculated here."""

    required_capability = Capability.PROCESS_SALES
    http_method_names = ["post"]

    def post(self, request):
        try:
            data = json.loads(request.body or b"{}")
            token = uuid.UUID(str(data.get("token", "")))
            lines = [(line["id"], line["qty"]) for line in data.get("lines", [])]
        except (ValueError, TypeError, KeyError, AttributeError):
            return JsonResponse({"ok": False, "error": "The sale could not be read. Reload the POS and try again."}, status=400)

        approver = None
        username = (data.get("approver_username") or "").strip()
        if username:
            # The sign-in backend's brute-force lock applies here too (shared with the sign-in pages).
            if throttling.is_locked(request, username):
                return JsonResponse({"ok": False, "error": "Too many failed attempts for this approver. Try again later."},
                                    status=429)
            approver = authenticate(request, username=username, password=data.get("approver_password") or "")
            if approver is None:
                return JsonResponse({"ok": False, "error": "Approver name or password is wrong."}, status=400)

        try:
            order, _created = services.create_sale(
                cashier=request.user, lines=lines, payment_method=data.get("payment_method", ""), token=token,
                cash_tendered=data.get("cash_tendered"), bank_reference=data.get("bank_reference", ""),
                discount_type=data.get("discount_type") or "", discount_value=data.get("discount_value"),
                discount_reason=data.get("discount_reason", ""), approver=approver,
                customer_name=data.get("customer_name", ""), customer_phone=data.get("customer_phone", ""),
                expected_total=data.get("expected_total"),
            )
        except ValidationError as error:
            return JsonResponse({"ok": False, "error": _errors(error), "code": getattr(error, "code", None)}, status=400)
        return JsonResponse({"ok": True, "number": order.number,
                             "receipt_url": reverse("pos:receipt", args=[order.number]) + "?new=1"})


# ---------------------------------------------------------------------------
# Sales history, receipts, refunds
# ---------------------------------------------------------------------------
class SalesListView(AnyCapabilityMixin, TemplateView):
    capabilities = SALES_VIEWERS
    template_name = "pos/sales_list.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        form = SalesFilterForm(self.request.GET or None, user=user)
        sales = services.visible_sales(user).select_related("cashier").annotate(lines=Count("items")).order_by("-created_at", "-pk")
        if form.is_bound and form.is_valid():
            d = form.cleaned_data
            if d["q"]:
                sales = sales.filter(number__icontains=d["q"].strip())
            if d["date_from"]:
                sales = sales.filter(created_at__date__gte=d["date_from"])
            if d["date_to"]:
                sales = sales.filter(created_at__date__lte=d["date_to"])
            if d.get("cashier"):
                sales = sales.filter(cashier=d["cashier"])
            if d["payment_method"]:
                sales = sales.filter(payment_method=d["payment_method"])
            if d["status"]:
                sales = sales.filter(status=d["status"])
        query = self.request.GET.copy()
        query.pop("page", None)
        ctx.update(filter_form=form, querystring=query.urlencode(), today=services.today_summary(user),
                   page_obj=Paginator(sales, settings.ORDER_PAGE_SIZE).get_page(self.request.GET.get("page")))
        return ctx


class SaleDetailView(AnyCapabilityMixin, TemplateView):
    capabilities = SALES_VIEWERS
    template_name = "pos/sale_detail.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        order = get_sale(user, self.kwargs["number"])
        payments = list(order.payments.select_related("verified_by", "refunded_by"))
        paid = next((p for p in payments if p.status == Payment.Status.PAID), None)
        can_refund = has_capability(user, Capability.REFUND_POS_SALES) and order.status != Order.Status.CANCELLED
        ctx.update(
            order=order, items=order.items.prefetch_related("stock_movements"), payments=payments,
            events=order.events.select_related("created_by"),
            reprints=order.receipt_prints.select_related("printed_by"),
            cash_refund=order.cash_movements.first(),
            can_verify=has_capability(user, Capability.VERIFY_PAYMENTS),
            can_refund=can_refund,
            refund_form=RefundForm() if can_refund else None,
            needs_drawer=bool(paid and paid.method == Order.PaymentMethod.CASH and paid.amount > 0),
        )
        return ctx


class ReceiptView(AnyCapabilityMixin, View):
    capabilities = SALES_VIEWERS

    def get(self, request, number):
        order = get_sale(request.user, number)
        size = "a4" if request.GET.get("size") == "a4" else "thermal"
        prints = order.receipt_prints.count()
        # The first print straight after the sale is the original; everything else is marked as a copy.
        original = (request.GET.get("new") == "1" and order.cashier_id == request.user.pk and prints == 0
                    and timezone.now() - order.created_at < timedelta(minutes=15))
        return render(request, "pos/receipt.html", {
            "order": order, "items": order.items.all(), "payment": order.payments.order_by("-created_at", "-pk").first(),
            "config": PosSettings.load(), "size": size, "original": original, "reprints": prints,
            "just_sold": request.GET.get("new") == "1",
        })


class ReprintView(AnyCapabilityMixin, View):
    capabilities = SALES_VIEWERS
    http_method_names = ["post"]

    def post(self, request, number):
        order = get_sale(request.user, number)
        services.record_reprint(order, request.user)
        size = "a4" if request.POST.get("size") == "a4" else "thermal"
        return redirect(reverse("pos:receipt", args=[order.number]) + f"?size={size}")


class RefundView(CapabilityRequiredMixin, View):
    required_capability = Capability.REFUND_POS_SALES
    http_method_names = ["post"]

    def post(self, request, number):
        order = get_sale(request.user, number)
        form = RefundForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Please give a reason and, for cash, the till that pays the refund.")
            return redirect("pos:sale_detail", number=number)
        try:
            services.refund_sale(order, request.user, form.cleaned_data["reason"], form.cleaned_data.get("drawer"))
        except ValidationError as error:
            messages.error(request, _errors(error))
        else:
            messages.success(request, f"Sale {order.number} voided: stock returned and the refund recorded.")
        return redirect("pos:sale_detail", number=number)


# ---------------------------------------------------------------------------
# Shifts and cash drawer
# ---------------------------------------------------------------------------
class ShiftListView(AnyCapabilityMixin, TemplateView):
    capabilities = SHIFT_VIEWERS
    template_name = "pos/shift_list.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        shifts = services.visible_shifts(user).select_related("cashier").order_by("-opened_at", "-pk")
        status = self.request.GET.get("status", "")
        if status in CashierShift.Status.values:
            shifts = shifts.filter(status=status)
        page = Paginator(shifts, settings.ORDER_PAGE_SIZE).get_page(self.request.GET.get("page"))
        rows = [(s, services.shift_summary(s) if s.is_open else None) for s in page]
        ctx.update(page_obj=page, rows=rows, status=status, querystring=f"status={status}" if status else "",
                   all_shifts=has_capability(user, Capability.MANAGE_SHIFTS),
                   my_open=services.current_shift(user) if has_capability(user, Capability.PROCESS_SALES) else None)
        return ctx


class ShiftDetailView(AnyCapabilityMixin, TemplateView):
    capabilities = SHIFT_VIEWERS
    template_name = "pos/shift_detail.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        shift = get_shift(user, self.kwargs["pk"])
        can_manage = shift.is_open and services.can_manage_shift(user, shift)
        ctx.update(shift=shift, summary=services.shift_summary(shift),
                   movements=shift.cash_movements.select_related("created_by", "order"),
                   sales=shift.sales.order_by("-created_at", "-pk"),
                   can_manage=can_manage, cash_form=CashMovementForm() if can_manage else None)
        return ctx


class CashMovementView(AnyCapabilityMixin, View):
    capabilities = SHIFT_VIEWERS
    http_method_names = ["post"]

    def post(self, request, pk):
        shift = get_shift(request.user, pk)
        form = CashMovementForm(request.POST)
        if not form.is_valid():
            messages.error(request, " ".join(e for errors in form.errors.values() for e in errors))
            return redirect("pos:shift_detail", pk=pk)
        try:
            movement = services.add_cash_movement(shift, request.user, form.cleaned_data["kind"],
                                                  form.cleaned_data["amount"], form.cleaned_data["reason"])
        except ValidationError as error:
            messages.error(request, _errors(error))
        else:
            messages.success(request, f"{movement.get_kind_display()}: LKR {movement.amount:,.2f} recorded.")
        return redirect("pos:shift_detail", pk=pk)


class CloseShiftView(AnyCapabilityMixin, View):
    capabilities = SHIFT_VIEWERS
    template_name = "pos/close_shift.html"

    def get_shift(self):
        shift = get_shift(self.request.user, self.kwargs["pk"])
        if not services.can_manage_shift(self.request.user, shift):
            raise PermissionDenied
        return shift

    def render(self, shift, form):
        return render(self.request, self.template_name, {"shift": shift, "summary": services.shift_summary(shift),
                                                         "form": form})

    def get(self, request, pk):
        shift = self.get_shift()
        if not shift.is_open:
            return redirect("pos:shift_detail", pk=pk)
        return self.render(shift, CloseShiftForm())

    def post(self, request, pk):
        shift = self.get_shift()
        form = CloseShiftForm(request.POST)
        if not form.is_valid():
            return self.render(shift, form)
        try:
            shift = services.close_shift(shift, request.user, form.cleaned_data["counted_cash"],
                                         form.cleaned_data["closing_note"])
        except ValidationError as error:
            form.add_error(None, _errors(error))
            return self.render(shift, form)
        messages.success(request, f"Shift {shift.code} closed. Difference: LKR {shift.difference:+,.2f}.")
        return redirect("pos:shift_detail", pk=pk)


class PosSettingsView(CapabilityRequiredMixin, UpdateView):
    required_capability = Capability.MANAGE_BUSINESS_SETTINGS
    form_class = PosSettingsForm
    template_name = "pos/settings.html"

    def get_object(self, queryset=None):
        return PosSettings.load()

    def form_valid(self, form):
        form.save()
        messages.success(self.request, "POS settings saved.")
        return redirect("pos:settings")

