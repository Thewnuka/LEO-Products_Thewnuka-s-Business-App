"""
Payment pages.

Customer:  submit bank-transfer details, start an online payment, gateway return page.
Gateway:   webhook (server-to-server; the ONLY way an online payment becomes paid).
Shared:    evidence viewer (order's customer or authorised staff only).
Staff:     approve/reject transfer evidence, record cash, record refunds.
"""
import mimetypes

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from apps.accounts.permissions import CapabilityRequiredMixin, CustomerRequiredMixin
from apps.accounts.roles import Capability, has_capability
from apps.orders.models import Order

from . import services
from .forms import BankTransferForm, NoteForm, ReviewPaymentForm
from .gateways import GatewayNotConfigured
from .models import Payment


# ---------------------------------------------------------------------------
# Customer
# ---------------------------------------------------------------------------
class SubmitBankTransferView(CustomerRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request, number):
        order = get_object_or_404(Order, number=number, customer=request.user)
        form = BankTransferForm(request.POST, request.FILES)
        if not form.is_valid():
            messages.error(request, " ".join(e for errors in form.errors.values() for e in errors))
            return redirect(order)
        try:
            services.submit_bank_transfer(order, request.user, form.cleaned_data["reference"], form.cleaned_data["evidence"])
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        else:
            messages.success(request, "Thank you. We've received your transfer details and will confirm the payment after checking it.")
        return redirect(order)


class StartOnlinePaymentView(CustomerRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request, number):
        order = get_object_or_404(Order, number=number, customer=request.user)
        try:
            payment, checkout = services.start_online_payment(order, request)
        except GatewayNotConfigured:
            messages.error(request, "Online payment is not available yet. Please contact us to pay another way.")
            return redirect(order)
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
            return redirect(order)
        # Auto-submitting form to the gateway's hosted payment page.
        # Fields as (name, value) pairs: a field may be called "items", which a template would mistake for dict.items.
        return render(request, "payments/online_redirect.html", {"order": order, "payment": payment, "checkout": checkout,
                                                                 "fields": list(checkout.fields.items())})


class OnlineReturnView(CustomerRequiredMixin, View):
    """Where the gateway sends the customer back. It never marks anything paid: only the webhook can."""

    def get(self, request, reference):
        payment = get_object_or_404(Payment, reference=reference, order__customer=request.user)
        if payment.status == Payment.Status.PAID:
            messages.success(request, "Your payment was received. Thank you!")
        elif payment.status == Payment.Status.FAILED:
            messages.error(request, "Your payment was not completed, so you have not been charged. "
                                    "You can try again with “Pay now”.")
        else:
            messages.info(request, "Thank you. We're waiting for the payment provider to confirm your payment; "
                                   "this page will show it as paid once confirmed.")
        return redirect(payment.order)


class OnlineCancelView(CustomerRequiredMixin, View):
    """
    Where the gateway sends the customer after they cancel on its payment page.
    Only noted in the payment's history: the payment stays open (so "Pay now" can be used
    again) and its status is still decided only by the gateway's verified notification.
    """

    def get(self, request, reference):
        payment = get_object_or_404(Payment, reference=reference, order__customer=request.user)
        if payment.status == Payment.Status.PAID:  # e.g. paid in another tab, then this page was reached
            messages.success(request, "Your payment was received. Thank you!")
        else:
            services.log(payment, "online_checkout_cancelled_by_customer", request.user)
            messages.warning(request, "You cancelled the online payment, so you have not been charged. "
                                      "Your order is saved; use “Pay now” whenever you're ready.")
        return redirect(payment.order)


@method_decorator(csrf_exempt, name="dispatch")  # called by the gateway's servers; verified by signature instead
class GatewayWebhookView(View):
    http_method_names = ["post"]

    def post(self, request, gateway):
        result = services.apply_gateway_notification(gateway, request.POST.dict())
        # Always 200 for well-formed requests so the gateway doesn't retry forever; the result is logged.
        return HttpResponse(result, content_type="text/plain")


class EvidenceView(View):
    """Stream a payment slip from private storage to the order's customer or authorised staff."""

    def get(self, request, reference):
        if not request.user.is_authenticated:
            raise Http404
        payment = get_object_or_404(Payment.objects.select_related("order"), reference=reference)
        user = request.user
        allowed = (payment.order.customer_id == user.pk) or has_capability(user, Capability.VIEW_ORDERS)
        if not allowed:
            raise Http404  # don't reveal that the payment exists
        if not payment.evidence:
            raise Http404
        content_type = payment.evidence_content_type or mimetypes.guess_type(payment.evidence.name)[0] or "application/octet-stream"
        # Images open in the browser; PDFs are downloaded, so they never run inside the site.
        response = FileResponse(payment.evidence.open("rb"), content_type=content_type,
                                as_attachment=content_type == "application/pdf",
                                filename=f"{payment.reference}{_ext(payment.evidence.name)}")
        response["Cache-Control"] = "private, no-store"
        return response


def _ext(name):
    return "." + name.rsplit(".", 1)[-1] if "." in name else ""


# ---------------------------------------------------------------------------
# Staff
# ---------------------------------------------------------------------------
class ReviewBankTransferView(CapabilityRequiredMixin, View):
    required_capability = Capability.VERIFY_PAYMENTS
    http_method_names = ["post"]

    def post(self, request, reference):
        payment = get_object_or_404(Payment.objects.select_related("order"), reference=reference)
        form = ReviewPaymentForm(request.POST)
        if not form.is_valid():
            raise PermissionDenied
        approve = form.cleaned_data["decision"] == "approve"
        try:
            services.review_bank_transfer(payment, request.user, approve, form.cleaned_data["note"])
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        else:
            messages.success(request, "Payment approved." if approve else "Payment rejected; the customer can submit new details.")
        return redirect(payment.order.get_staff_url())


class RecordCashView(CapabilityRequiredMixin, View):
    required_capability = Capability.RECORD_CASH_PAYMENTS
    http_method_names = ["post"]

    def post(self, request, number):
        order = get_object_or_404(Order, number=number)
        form = NoteForm(request.POST)
        form.is_valid()
        try:
            payment = services.record_cash_payment(order, request.user, form.cleaned_data.get("note", ""))
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        else:
            messages.success(request, f"Cash of LKR {payment.amount:,.2f} recorded for {order.number}.")
        return redirect("orders:staff_detail", number=number)


class RecordRefundView(CapabilityRequiredMixin, View):
    required_capability = Capability.MANAGE_PAYMENTS
    http_method_names = ["post"]

    def post(self, request, reference):
        payment = get_object_or_404(Payment.objects.select_related("order"), reference=reference)
        form = NoteForm(request.POST)
        form.is_valid()
        try:
            services.record_refund(payment, request.user, form.cleaned_data.get("note", ""))
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        else:
            messages.success(request, f"Refund recorded for {payment.reference}.")
        return redirect(payment.order.get_staff_url())
