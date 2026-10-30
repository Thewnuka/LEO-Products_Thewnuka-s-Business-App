"""
Checkout, customer order pages and staff order management.

Customers (CustomerRequiredMixin) only ever see orders where customer = themselves;
anyone else's order number gives 404. Staff pages need VIEW_ORDERS, and each
action its own capability (MANAGE_ORDERS, VERIFY_PAYMENTS, RECORD_CASH_PAYMENTS,
MANAGE_PAYMENTS for refunds, MANAGE_BUSINESS_SETTINGS for settings).
"""
import uuid
from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import CreateView, TemplateView, UpdateView

from apps.accounts.permissions import CapabilityRequiredMixin, CustomerRequiredMixin
from apps.accounts.roles import Capability, has_capability
from apps.payments.forms import BankTransferForm
from apps.payments.gateways import online_payment_available
from apps.shop import services as shop

from . import services
from .forms import CancelOrderForm, CheckoutForm, CheckoutSettingsForm, DeliveryZoneForm, OrderFilterForm, StatusChangeForm
from .models import CheckoutSettings, DeliveryZone, Order

SESSION_CHECKOUT = "checkout"


# ---------------------------------------------------------------------------
# Checkout (signed-in customers)
# ---------------------------------------------------------------------------
def _serialise(cleaned):
    data = {k: v for k, v in cleaned.items() if k != "delivery_zone"}
    data["delivery_zone"] = cleaned["delivery_zone"].pk if cleaned.get("delivery_zone") else None
    return data


def _restore(data):
    restored = dict(data)
    restored["delivery_zone"] = DeliveryZone.objects.filter(pk=data.get("delivery_zone"), is_active=True).first() \
        if data.get("delivery_zone") else None
    return restored


class CheckoutView(CustomerRequiredMixin, View):
    template_name = "orders/checkout.html"

    def get_cart_quote(self, fulfilment=None, zone=None):
        cart = shop.get_cart_for_user(self.request.user)
        return services.quote(cart, fulfilment or Order.Fulfilment.PICKUP, zone)

    def get(self, request):
        q = self.get_cart_quote()
        if not q.lines:
            messages.info(request, "Your cart is empty.")
            return redirect("shop:cart")
        saved = request.session.get(SESSION_CHECKOUT, {}).get("data")
        user = request.user
        initial = saved or {"full_name": user.get_full_name(), "phone": user.phone_number}
        if saved and saved.get("delivery_zone"):
            initial = {**saved, "delivery_zone": saved["delivery_zone"]}
        return self.render(CheckoutForm(initial=initial), q)

    def post(self, request):
        form = CheckoutForm(request.POST)
        if not form.is_valid():
            return self.render(form, self.get_cart_quote())
        d = form.cleaned_data
        q = self.get_cart_quote(d["fulfilment"], d.get("delivery_zone"))
        if not q.lines:
            messages.info(request, "Your cart is empty.")
            return redirect("shop:cart")
        request.session[SESSION_CHECKOUT] = {"token": str(uuid.uuid4()), "data": _serialise(d), "total": str(q.total)}
        return redirect("orders:checkout_review")

    def render(self, form, q):
        config = form.config
        return render(self.request, self.template_name, {
            "form": form, "quote": q, "config": config,
            "can_checkout": bool(form.fields["fulfilment"].choices and form.fields["payment_method"].choices),
            "online_available": online_payment_available(),
            # Lets checkout.js hide methods that don't apply; the form re-validates on the server.
            "payment_map": {f: [str(m) for m in services.payment_options(f, config)]
                            for f, _label in form.fields["fulfilment"].choices},
        })


class CheckoutReviewView(CustomerRequiredMixin, View):
    template_name = "orders/review.html"

    def load(self):
        state = self.request.session.get(SESSION_CHECKOUT)
        if not state:
            return None, None, None
        details = _restore(state["data"])
        cart = shop.get_cart_for_user(self.request.user)
        return state, details, services.quote(cart, details["fulfilment"], details.get("delivery_zone"))

    def get(self, request):
        state, details, q = self.load()
        if state is None:
            return redirect("orders:checkout")
        if not q.lines:
            return redirect("shop:cart")
        if str(q.total) != state["total"]:
            state["total"] = str(q.total)
            request.session[SESSION_CHECKOUT] = state
            messages.warning(request, "Prices or charges changed. Please check the updated total.")
        return render(request, self.template_name, {"state": state, "details": details, "quote": q,
                                                    "config": CheckoutSettings.load()})

    def post(self, request):
        token = request.POST.get("token", "")
        # Double click / second tab: this page's order may already exist. Show it instead of placing another.
        if _is_uuid(token):
            existing = Order.objects.filter(checkout_token=token, customer=request.user).first()
            if existing:
                return redirect(existing)
        state, details, q = self.load()
        if state is None:
            messages.info(request, "Please fill in your details again.")
            return redirect("orders:checkout")
        if token != state["token"]:
            messages.warning(request, "Your checkout details changed. Please review your order again.")
            return redirect("orders:checkout_review")
        try:
            order, created = services.place_order(request.user, details, uuid.UUID(state["token"]),
                                                  expected_total=Decimal(state["total"]))
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
            if getattr(error, "code", None) == "total_changed":
                state["total"] = str(q.total)
                request.session[SESSION_CHECKOUT] = state
                return redirect("orders:checkout_review")
            return redirect("shop:cart")
        request.session.pop(SESSION_CHECKOUT, None)
        if created:
            messages.success(request, f"Thank you! Your order {order.number} has been placed.")
        return redirect(f"{reverse('orders:detail', args=[order.number])}?placed=1")


def _is_uuid(value):
    try:
        uuid.UUID(str(value))
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Customer: my orders
# ---------------------------------------------------------------------------
class MyOrdersView(CustomerRequiredMixin, TemplateView):
    template_name = "orders/customer/order_list.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        orders = Order.objects.filter(customer=self.request.user).annotate(lines=Count("items")).order_by("-created_at", "-pk")
        ctx["page_obj"] = Paginator(orders, settings.ORDER_PAGE_SIZE).get_page(self.request.GET.get("page"))
        ctx["querystring"] = ""
        return ctx


class MyOrderDetailView(CustomerRequiredMixin, TemplateView):
    template_name = "orders/customer/order_detail.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        order = get_object_or_404(Order.objects.prefetch_related("items", "events", "payments"),
                                  number=self.kwargs["number"], customer=self.request.user)
        latest = order.payments.order_by("-created_at", "-pk").first()
        ctx.update(order=order, latest_payment=latest, config=CheckoutSettings.load(),
                   just_placed=self.request.GET.get("placed") == "1",
                   can_cancel=services.customer_can_cancel(order), cancel_form=CancelOrderForm(),
                   bank_form=BankTransferForm(), online_available=online_payment_available(),
                   needs_bank_details=(order.payment_method == Order.PaymentMethod.BANK_TRANSFER and order.is_open
                                       and order.payment_status == Order.PaymentStatus.PENDING))
        return ctx


class MyOrderCancelView(CustomerRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request, number):
        order = get_object_or_404(Order, number=number, customer=request.user)
        form = CancelOrderForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Please tell us why you are cancelling.")
            return redirect(order)
        try:
            services.cancel_order(order, request.user, form.cleaned_data["reason"], by_customer=True)
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        else:
            messages.success(request, f"Order {order.number} was cancelled.")
        return redirect(order)


# ---------------------------------------------------------------------------
# Staff
# ---------------------------------------------------------------------------
class StaffOrderAccess(CapabilityRequiredMixin):
    required_capability = Capability.VIEW_ORDERS


def filter_orders(form):
    qs = Order.objects.select_related("customer").annotate(lines=Count("items")).order_by("-created_at", "-pk")
    if not (form.is_bound and form.is_valid()):
        return qs
    d = form.cleaned_data
    if d["q"]:
        q = d["q"].strip()
        qs = qs.filter(Q(number__icontains=q) | Q(full_name__icontains=q) | Q(phone__icontains=q) | Q(email__icontains=q))
    if d["status"] == "OPEN":
        qs = qs.exclude(status__in=[Order.Status.COMPLETED, Order.Status.CANCELLED])
    elif d["status"]:
        qs = qs.filter(status=d["status"])
    if d["payment_method"]:
        qs = qs.filter(payment_method=d["payment_method"])
    if d["payment_status"]:
        qs = qs.filter(payment_status=d["payment_status"])
    if d["date_from"]:
        qs = qs.filter(created_at__date__gte=d["date_from"])
    if d["date_to"]:
        qs = qs.filter(created_at__date__lte=d["date_to"])
    return qs


class StaffOrderListView(StaffOrderAccess, TemplateView):
    template_name = "orders/staff/order_list.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        form = OrderFilterForm(self.request.GET or None)
        page = Paginator(filter_orders(form), settings.ORDER_PAGE_SIZE).get_page(self.request.GET.get("page"))
        query = self.request.GET.copy()
        query.pop("page", None)
        ctx.update(filter_form=form, page_obj=page, querystring=query.urlencode(),
                   to_verify=Order.objects.filter(payment_status=Order.PaymentStatus.PENDING_VERIFICATION).count(),
                   pending=Order.objects.filter(status=Order.Status.PENDING).count())
        return ctx


class StaffOrderDetailView(StaffOrderAccess, TemplateView):
    template_name = "orders/staff/order_detail.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        order = get_object_or_404(Order.objects.select_related("customer", "cancelled_by"), number=self.kwargs["number"])
        user = self.request.user
        payments = list(order.payments.select_related("verified_by", "refunded_by").prefetch_related("events__created_by"))
        # One timeline: order status changes and payment events, oldest first.
        history = [{"at": e.created_at, "title": e.to_label, "by": e.created_by, "note": e.note, "strong": True}
                   for e in order.events.select_related("created_by")]
        history += [{"at": pe.created_at, "title": f"{p.reference}: {pe.label}", "by": pe.created_by,
                     "note": pe.detail.get("note", ""), "strong": False} for p in payments for pe in p.events.all()]
        history.sort(key=lambda entry: entry["at"])
        ctx.update(
            order=order,
            items=order.items.prefetch_related("stock_movements"),
            history=history,
            payments=payments,
            transitions=services.allowed_transitions(order) if has_capability(user, Capability.MANAGE_ORDERS) else [],
            can_manage=has_capability(user, Capability.MANAGE_ORDERS),
            can_verify=has_capability(user, Capability.VERIFY_PAYMENTS),
            can_cash=has_capability(user, Capability.RECORD_CASH_PAYMENTS),
            can_refund=has_capability(user, Capability.MANAGE_PAYMENTS),
            can_cancel=has_capability(user, Capability.MANAGE_ORDERS) and order.status in services.STAFF_CANCELLABLE,
        )
        return ctx


class StaffStatusView(CapabilityRequiredMixin, View):
    required_capability = Capability.MANAGE_ORDERS
    http_method_names = ["post"]

    def post(self, request, number):
        order = get_object_or_404(Order, number=number)
        form = StatusChangeForm(request.POST)
        if not form.is_valid() or form.cleaned_data["to_status"] == Order.Status.CANCELLED:
            messages.error(request, "Choose a valid status.")
            return redirect("orders:staff_detail", number=number)
        try:
            order = services.change_status(order, form.cleaned_data["to_status"], request.user, form.cleaned_data["note"])
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        else:
            messages.success(request, f"Order {order.number} is now {order.get_status_display().lower()}.")
        return redirect("orders:staff_detail", number=number)


class StaffCancelView(CapabilityRequiredMixin, View):
    required_capability = Capability.MANAGE_ORDERS
    http_method_names = ["post"]

    def post(self, request, number):
        order = get_object_or_404(Order, number=number)
        form = CancelOrderForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Please give a reason for cancelling.")
            return redirect("orders:staff_detail", number=number)
        try:
            order = services.cancel_order(order, request.user, form.cleaned_data["reason"])
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        else:
            extra = " The customer has paid: record the refund once it is made." if order.payment_status == Order.PaymentStatus.REFUND_DUE else ""
            messages.success(request, f"Order {order.number} cancelled and its stock put back.{extra}")
        return redirect("orders:staff_detail", number=number)


class CheckoutSettingsView(CapabilityRequiredMixin, UpdateView):
    required_capability = Capability.MANAGE_BUSINESS_SETTINGS
    form_class = CheckoutSettingsForm
    template_name = "orders/staff/settings.html"

    def get_object(self, queryset=None):
        return CheckoutSettings.load()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["zones"] = DeliveryZone.objects.annotate(order_count=Count("orders"))
        ctx["online_available"] = online_payment_available()
        ctx["gateway_name"] = settings.PAYMENT_GATEWAY
        return ctx

    def form_valid(self, form):
        form.save()
        messages.success(self.request, "Delivery and payment settings saved.")
        return redirect("orders:settings")


class ZoneCreateView(CapabilityRequiredMixin, CreateView):
    required_capability = Capability.MANAGE_BUSINESS_SETTINGS
    model = DeliveryZone
    form_class = DeliveryZoneForm
    template_name = "orders/staff/zone_form.html"

    def form_valid(self, form):
        zone = form.save()
        messages.success(self.request, f"Delivery area “{zone.name}” added.")
        return redirect("orders:settings")


class ZoneUpdateView(CapabilityRequiredMixin, UpdateView):
    required_capability = Capability.MANAGE_BUSINESS_SETTINGS
    model = DeliveryZone
    form_class = DeliveryZoneForm
    template_name = "orders/staff/zone_form.html"
    context_object_name = "zone"

    def form_valid(self, form):
        zone = form.save()
        messages.success(self.request, f"Delivery area “{zone.name}” saved. Existing orders keep the fee they were charged.")
        return redirect("orders:settings")
