"""
Payment logic. Every status change is a conditional UPDATE ("only if the
payment is still in state X"), so double clicks, two staff members acting at
once, or a gateway sending the same notification twice can never confirm,
reject or refund a payment twice.

Nothing becomes PAID by itself:
  CASH           staff record that the cash was received;
  BANK_TRANSFER  the customer submits a reference + evidence (PENDING_VERIFICATION),
                 then staff approve or reject it;
  ONLINE         only a signature-verified gateway notification with the right
                 amount and currency marks it PAID.
"""
import io
import logging
import secrets

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from PIL import Image, UnidentifiedImageError

from apps.orders.models import Order

from .gateways import GatewayNotConfigured, InvalidNotification, get_gateway
from .models import Payment, PaymentEvent

logger = logging.getLogger(__name__)
S = Payment.Status
M = Order.PaymentMethod


class PaymentError(ValidationError):
    """A payment action that is not allowed (shown to the user)."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _new_reference():
    return f"PAY-{timezone.now():%y%m%d}-{secrets.token_hex(3).upper()}"


def create_payment(order, *, status=S.PENDING, **fields):
    """
    Create a payment attempt for the order's total with a unique reference.
    (The database also guarantees at most one open attempt per order.)
    """
    for _ in range(10):
        reference = _new_reference()
        if not Payment.objects.filter(reference=reference).exists():
            return Payment.objects.create(order=order, method=order.payment_method, amount=order.total,
                                          status=status, reference=reference, **fields)
    raise PaymentError("Could not create a payment reference. Please try again.")


def log(payment, event, user=None, **detail):
    PaymentEvent.objects.create(payment=payment, event=event, created_by=user if getattr(user, "is_authenticated", False) else None,
                                detail=detail)


def sync_order_payment_status(order):
    """Recalculate Order.payment_status from its payments."""
    payments = set(Payment.objects.filter(order=order).values_list("status", flat=True))
    P = Order.PaymentStatus
    if S.PAID in payments:
        summary = P.REFUND_DUE if order.status == Order.Status.CANCELLED else P.PAID
    elif S.REFUNDED in payments:
        summary = P.REFUNDED
    elif S.PENDING_VERIFICATION in payments:
        summary = P.PENDING_VERIFICATION
    else:
        summary = P.PENDING
    Order.objects.filter(pk=order.pk).update(payment_status=summary, updated_at=timezone.now())
    order.payment_status = summary
    return summary


def _transition(payment, from_statuses, to_status, **fields):
    """Conditional update: returns True only for the request that actually made the change."""
    now = timezone.now()
    changed = Payment.objects.filter(pk=payment.pk, status__in=list(from_statuses)).update(
        status=to_status, updated_at=now, **fields)
    if changed:
        payment.refresh_from_db()
    return bool(changed)


def _notify(order, kind, **context):
    from apps.orders.notifications import notify_customer

    notify_customer(order, kind, **context)


# ---------------------------------------------------------------------------
# Evidence files
# ---------------------------------------------------------------------------
ALLOWED_EVIDENCE = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp", "pdf": "application/pdf"}


def validate_evidence(upload):
    """Check a bank-transfer slip: JPG, PNG, WebP or PDF, within the size limit, and really that format."""
    if upload.size > settings.PAYMENT_EVIDENCE_MAX_BYTES:
        raise ValidationError(f"The file is too large. The maximum is {settings.PAYMENT_EVIDENCE_MAX_BYTES // (1024 * 1024)} MB.")
    ext = upload.name.rsplit(".", 1)[-1].lower() if "." in upload.name else ""
    if ext not in ALLOWED_EVIDENCE:
        raise ValidationError("Upload a photo or screenshot (JPG, PNG, WebP) or a PDF.")
    upload.seek(0)
    head = upload.read(2048)
    upload.seek(0)
    if ext == "pdf":
        if not head.startswith(b"%PDF-"):
            raise ValidationError("This file is not a valid PDF.")
        return "application/pdf"
    try:
        with Image.open(io.BytesIO(upload.read())) as img:
            if img.format not in ("JPEG", "PNG", "WEBP"):
                raise ValidationError("Upload a JPG, PNG or WebP image, or a PDF.")
            if img.width * img.height > 40_000_000:
                raise ValidationError("The image dimensions are too large.")
            img.verify()
            fmt = img.format
    except ValidationError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise ValidationError("This file is not a valid image, or it is damaged.")
    finally:
        upload.seek(0)
    return {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}[fmt]


# ---------------------------------------------------------------------------
# Bank transfer
# ---------------------------------------------------------------------------
@transaction.atomic
def submit_bank_transfer(order, user, reference, evidence):
    """Customer sends transfer details. The payment waits for staff verification; it is NOT paid yet."""
    order = Order.objects.select_for_update().get(pk=order.pk)
    if order.payment_method != M.BANK_TRANSFER:
        raise PaymentError("This order is not paid by bank transfer.")
    if order.status == Order.Status.CANCELLED:
        raise PaymentError("This order has been cancelled.")
    if order.payment_status == Order.PaymentStatus.PAID:
        raise PaymentError("This order is already paid.")
    content_type = validate_evidence(evidence)
    open_payment = Payment.objects.select_for_update().filter(order=order, status__in=Payment.OPEN_STATUSES).first()
    fields = {"bank_reference": reference.strip(), "submitted_at": timezone.now(), "evidence_content_type": content_type}
    if open_payment and open_payment.status == S.PENDING_VERIFICATION:
        raise PaymentError("Your transfer details were already submitted and are waiting to be checked.")
    if open_payment:
        payment = open_payment
        for key, value in fields.items():
            setattr(payment, key, value)
        payment.evidence = evidence
        payment.status = S.PENDING_VERIFICATION
        payment.save()
    else:  # after a rejected attempt: a new attempt
        payment = create_payment(order, status=S.PENDING_VERIFICATION, **fields)
        payment.evidence = evidence
        payment.save(update_fields=["evidence", "updated_at"])
    log(payment, "bank_transfer_submitted", user, reference=payment.bank_reference)
    sync_order_payment_status(order)
    return payment


@transaction.atomic
def review_bank_transfer(payment, staff, approve, note=""):
    """Staff approve (-> PAID) or reject (-> REJECTED, customer may resubmit) submitted evidence."""
    if payment.method != M.BANK_TRANSFER:
        raise PaymentError("This is not a bank-transfer payment.")
    if not approve and not note.strip():
        raise PaymentError("Please give a reason for rejecting, so the customer knows what to fix.")
    now = timezone.now()
    if approve:
        if Payment.objects.filter(order=payment.order, status=S.PAID).exists():
            raise PaymentError("This order already has a confirmed payment.")
        done = _transition(payment, [S.PENDING_VERIFICATION], S.PAID, verified_by=staff, verified_at=now, paid_at=now,
                           verification_note=note.strip())
    else:
        done = _transition(payment, [S.PENDING_VERIFICATION], S.REJECTED, verified_by=staff, verified_at=now,
                           verification_note=note.strip())
    if not done:
        raise PaymentError(f"This payment is already {payment.get_status_display().lower()}; nothing was changed.")
    log(payment, "bank_transfer_approved" if approve else "bank_transfer_rejected", staff, note=note.strip())
    order = Order.objects.get(pk=payment.order_id)
    sync_order_payment_status(order)
    if approve and order.channel == Order.Channel.POS:
        _complete_pos_sale(order, staff)
    _notify(order, "payment_approved" if approve else "payment_rejected", payment=payment)
    return payment


def _complete_pos_sale(order, staff):
    """An in-store sale paid by bank transfer is completed once the transfer is approved."""
    from apps.orders.models import OrderStatusEvent

    now = timezone.now()
    if Order.objects.filter(pk=order.pk, status=Order.Status.PENDING).update(
            status=Order.Status.COMPLETED, completed_at=now, updated_at=now):
        OrderStatusEvent.objects.create(order=order, from_status=Order.Status.PENDING, to_status=Order.Status.COMPLETED,
                                        created_by=staff, note="Bank transfer approved")


# ---------------------------------------------------------------------------
# Cash
# ---------------------------------------------------------------------------
@transaction.atomic
def record_cash_payment(order, staff, note=""):
    """Staff confirm the cash for the full order total was received."""
    order = Order.objects.select_for_update().get(pk=order.pk)
    if order.payment_method != M.CASH:
        raise PaymentError("This order is not paid in cash.")
    if order.status == Order.Status.CANCELLED:
        raise PaymentError("This order has been cancelled.")
    payment = Payment.objects.filter(order=order, status__in=Payment.OPEN_STATUSES).first()
    now = timezone.now()
    if payment is None:
        if Payment.objects.filter(order=order, status=S.PAID).exists():
            raise PaymentError("Cash for this order has already been recorded.")
        payment = create_payment(order)
    if not _transition(payment, [S.PENDING], S.PAID, verified_by=staff, verified_at=now, paid_at=now,
                       verification_note=note.strip() or "Cash received"):
        raise PaymentError("Cash for this order has already been recorded.")
    log(payment, "cash_received", staff, amount=str(payment.amount))
    sync_order_payment_status(order)
    return payment


# ---------------------------------------------------------------------------
# Refunds (Owner)
# ---------------------------------------------------------------------------
@transaction.atomic
def record_refund(payment, owner, note):
    """Record that a paid amount was given back (only for cancelled orders)."""
    if not note.strip():
        raise PaymentError("Please describe how the refund was made (e.g. bank transfer reference).")
    order = Order.objects.select_for_update().get(pk=payment.order_id)
    if order.status != Order.Status.CANCELLED:
        raise PaymentError("Refunds are recorded for cancelled orders. Cancel the order first.")
    if not _transition(payment, [S.PAID], S.REFUNDED, refunded_by=owner, refunded_at=timezone.now(), refund_note=note.strip()):
        raise PaymentError("This payment is not marked as paid, or was already refunded.")
    log(payment, "refunded", owner, note=note.strip())
    sync_order_payment_status(order)
    return payment


def close_open_payments_for_cancelled_order(order, user):
    """When an order is cancelled, unpaid attempts are closed (they can no longer be paid)."""
    for payment in Payment.objects.filter(order=order, status__in=Payment.OPEN_STATUSES):
        new = S.REJECTED if payment.status == S.PENDING_VERIFICATION else S.FAILED
        if _transition(payment, [payment.status], new, verification_note="Order cancelled"):
            log(payment, "closed_order_cancelled", user)
    sync_order_payment_status(order)


# ---------------------------------------------------------------------------
# Online gateway
# ---------------------------------------------------------------------------
@transaction.atomic
def start_online_payment(order, request):
    """Prepare a hosted-checkout request. Raises GatewayNotConfigured when online payment is off."""
    gateway = get_gateway()
    if gateway is None:
        raise GatewayNotConfigured("Online payment is not set up for this shop yet.")
    order = Order.objects.select_for_update().get(pk=order.pk)
    if order.payment_method != M.ONLINE:
        raise PaymentError("This order is not paid online.")
    if order.status == Order.Status.CANCELLED or order.payment_status == Order.PaymentStatus.PAID:
        raise PaymentError("This order can't be paid now.")
    payment = Payment.objects.filter(order=order, status=S.PENDING).first() or create_payment(order)
    if payment.gateway != gateway.name:
        payment.gateway = gateway.name
        payment.save(update_fields=["gateway", "updated_at"])
    from django.urls import reverse

    checkout = gateway.build_checkout(
        payment,
        return_url=request.build_absolute_uri(reverse("payments:online_return", args=[payment.reference])),
        cancel_url=request.build_absolute_uri(reverse("orders:detail", args=[order.number])),
        notify_url=request.build_absolute_uri(reverse("payments:webhook", args=[gateway.name])),
        customer=order.customer,
    )
    log(payment, "online_checkout_started", request.user, gateway=gateway.name)
    return payment, checkout


def apply_gateway_notification(gateway_name, data):
    """
    Handle a server-to-server notification. Returns a short result string.
    Invalid or unverifiable notifications are logged and ignored (never trusted).
    """
    gateway = get_gateway(gateway_name)
    if gateway is None:
        logger.warning("Payment notification for unconfigured gateway %s ignored", gateway_name)
        return "ignored: gateway not configured"
    try:
        note = gateway.parse_notification(data)
    except InvalidNotification as error:
        logger.warning("Rejected %s notification: %s", gateway_name, error)
        return "ignored: invalid notification"

    with transaction.atomic():
        payment = Payment.objects.select_for_update().filter(reference=note.payment_reference, method=M.ONLINE).first()
        if payment is None:
            return "ignored: unknown payment"
        if note.amount != payment.amount or note.currency != payment.currency:
            log(payment, "notification_amount_mismatch", None, **note.safe_payload)
            logger.error("Amount/currency mismatch for %s", payment.reference)
            return "ignored: amount mismatch"
        log(payment, f"gateway_{note.outcome}", None, **note.safe_payload)
        if note.outcome == "paid":
            if Payment.objects.filter(order=payment.order, status=S.PAID).exclude(pk=payment.pk).exists():
                return "ignored: order already paid"
            now = timezone.now()
            if not _transition(payment, [S.PENDING, S.FAILED], S.PAID, transaction_id=note.transaction_id[:100],
                               gateway_status=note.gateway_status, paid_at=now, verified_at=now,
                               verification_note=f"Verified {gateway.display_name} notification"):
                return "duplicate: already processed"
            order = Order.objects.get(pk=payment.order_id)
            sync_order_payment_status(order)
            _notify(order, "payment_approved", payment=payment)
            return "paid"
        if note.outcome in ("failed", "cancelled"):
            _transition(payment, [S.PENDING], S.FAILED, gateway_status=note.gateway_status)
            sync_order_payment_status(Order.objects.get(pk=payment.order_id))
            return note.outcome
        return note.outcome  # pending / chargeback: logged for staff to review
