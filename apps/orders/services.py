"""
Order logic: checkout, status workflow, cancellation.

STOCK POLICY
------------
Stock is DEDUCTED WHEN THE ORDER IS PLACED, inside the same database
transaction that creates the order. Each line goes through
inventory.services.record_movement (movement type "Sale (order)"), which
refuses to go below zero with a conditional UPDATE, so two customers buying
the last packet at the same moment can't both succeed: one order is placed,
the other gets "not enough stock" and nothing is saved for it.
If the order is CANCELLED (before it is delivered/completed), every line is put
back with an "Order cancelled (restock)" movement. Database constraints allow
one sale and at most one restock movement per order line, so stock can never
be deducted or restored twice.
"""
import uuid
from dataclasses import dataclass
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.inventory.models import StockMovement
from apps.inventory.services import record_movement
from apps.shop import services as shop

from .models import CheckoutSettings, DeliveryZone, Order, OrderItem, OrderStatusEvent

St = Order.Status
F = Order.Fulfilment
PM = Order.PaymentMethod


class OrderError(ValidationError):
    """An order action that is not allowed (shown to the user)."""


# ---------------------------------------------------------------------------
# Options and totals
# ---------------------------------------------------------------------------
def fulfilment_options(config=None):
    config = config or CheckoutSettings.load()
    options = []
    if config.delivery_enabled and DeliveryZone.objects.filter(is_active=True).exists():
        options.append(F.DELIVERY)
    if config.pickup_enabled:
        options.append(F.PICKUP)
    return options


def payment_options(fulfilment, config=None):
    """Payment methods offered for a fulfilment type (online only when a gateway is configured)."""
    from apps.payments.gateways import online_payment_available

    config = config or CheckoutSettings.load()
    options = []
    if (fulfilment == F.DELIVERY and config.cash_on_delivery_enabled) or (fulfilment == F.PICKUP and config.cash_on_pickup_enabled):
        options.append(PM.CASH)
    if config.bank_transfer_available:
        options.append(PM.BANK_TRANSFER)
    if online_payment_available():
        options.append(PM.ONLINE)
    return options


@dataclass
class Quote:
    lines: list
    subtotal: Decimal
    delivery_fee: Decimal
    total: Decimal
    problems: list


def quote(cart, fulfilment, zone=None):
    """Prices and totals from the database (never from the browser), plus any stock problems."""
    summary = shop.summarize_cart(cart)
    problems = [f"{line.item.variation.product.name} ({line.item.variation.display_name}): {line.note}"
                for line in summary.lines if line.status != "ok"]
    lines = [line for line in summary.lines if line.status != "unavailable"]
    subtotal = sum((line.unit_price * line.item.quantity for line in lines), Decimal("0.00"))
    fee = zone.fee_for(subtotal) if (fulfilment == F.DELIVERY and zone) else Decimal("0.00")
    return Quote(lines=lines, subtotal=subtotal, delivery_fee=fee, total=subtotal + fee, problems=problems)


# ---------------------------------------------------------------------------
# Placing an order
# ---------------------------------------------------------------------------
def next_order_number(series="LEO"):
    """Next number in a yearly series: LEO-2026-00001 (online) or POS-2026-00001 (in-store)."""
    prefix = f"{series}-{timezone.localdate():%Y}-"
    last = Order.objects.filter(number__startswith=prefix).order_by("-number").values_list("number", flat=True).first()
    return f"{prefix}{(int(last.rsplit('-', 1)[1]) + 1 if last else 1):05d}"


def place_order(customer, details, checkout_token, expected_total=None):
    """
    Create the order from the customer's cart in ONE transaction: re-check stock,
    deduct it, copy prices, create the payment record and empty the cart.

    `details`: cleaned checkout data (full_name, phone, fulfilment, delivery_zone,
    address_line1, address_line2, city, delivery_instructions, payment_method).
    `checkout_token`: from the review page; placing twice with the same token
    returns the first order instead of creating another.
    `expected_total`: the total the customer saw; if prices changed meanwhile the
    order is refused so they can review the new total.
    """
    for attempt in range(3):
        existing = Order.objects.filter(checkout_token=checkout_token, customer=customer).first()
        if existing:
            return existing, False
        try:
            with transaction.atomic():
                return _place_order(customer, details, checkout_token, expected_total), True
        except IntegrityError:
            # Either the same token was used by a simultaneous request (the loop then returns
            # its order) or another order took the same number at the same moment (try again).
            if attempt == 2:
                raise


def _place_order(customer, details, checkout_token, expected_total):
    from apps.payments.services import create_payment

    config = CheckoutSettings.load()
    fulfilment, method = details["fulfilment"], details["payment_method"]
    if fulfilment not in fulfilment_options(config):
        raise OrderError("That delivery option is not available.")
    if method not in payment_options(fulfilment, config):
        raise OrderError("That payment method is not available.")
    zone = details.get("delivery_zone") if fulfilment == F.DELIVERY else None
    if fulfilment == F.DELIVERY and (zone is None or not zone.is_active):
        raise OrderError("Please choose a delivery area.")

    cart = shop.get_cart_for_user(customer)
    q = quote(cart, fulfilment, zone)
    if not q.lines:
        raise OrderError("Your cart is empty.")
    if q.problems:
        raise OrderError("Some items in your cart changed: " + "; ".join(q.problems))
    if expected_total is not None and Decimal(str(expected_total)) != q.total:
        raise OrderError(f"Prices or charges changed since you reviewed your order. The new total is LKR {q.total:,.2f}; "
                         "please review it again.", code="total_changed")

    order = Order.objects.create(
        number=next_order_number(), customer=customer, checkout_token=checkout_token,
        full_name=details["full_name"], phone=details["phone"], email=customer.email,
        fulfilment=fulfilment, delivery_zone=zone, delivery_zone_name=zone.name if zone else "",
        address_line1=details.get("address_line1", "") if zone else "", address_line2=details.get("address_line2", "") if zone else "",
        city=details.get("city", "") if zone else "", delivery_instructions=details.get("delivery_instructions", ""),
        subtotal=q.subtotal, delivery_fee=q.delivery_fee, total=q.total, payment_method=method,
    )
    add_items_and_deduct_stock(order, [(line.item.variation, line.item.quantity, line.unit_price) for line in q.lines],
                               customer, reason=f"Online order {order.number}", hint="Please update your cart.")
    create_payment(order)
    OrderStatusEvent.objects.create(order=order, to_status=St.PENDING, created_by=customer, note="Order placed")
    cart.items.all().delete()
    _notify_on_commit(order, "placed")
    return order


def add_items_and_deduct_stock(order, lines, user, *, reason, hint=""):
    """
    Create the order lines (name, size, SKU and price copied) and deduct each from stock
    with one SALE ledger movement. `lines`: (variation, quantity, unit_price).
    Must run inside the caller's transaction; a stock shortage raises OrderError and
    the whole order is rolled back. Shared by online checkout and the POS.
    """
    # Lock stock rows in a fixed order (by stock record id) to avoid deadlocks between simultaneous orders.
    for v, quantity, unit_price in sorted(lines, key=lambda line: line[0].inventory_item.pk):
        item = OrderItem.objects.create(
            order=order, variation=v, product_name=v.product.name, variation_name=v.display_name, sku=v.sku,
            unit_price=unit_price, quantity=quantity, line_total=unit_price * quantity)
        try:
            record_movement(v.inventory_item, StockMovement.Type.SALE, quantity, user, reason=reason, order_item=item)
        except ValidationError:
            v.inventory_item.refresh_from_db()  # the caller's copy may be stale: report what is really left
            available = shop.available_stock(v)
            raise OrderError(f"Sorry, only {available} of {v.product.name} ({v.display_name}) left. {hint}".strip())


# ---------------------------------------------------------------------------
# Status workflow
# ---------------------------------------------------------------------------
TRANSITIONS = {
    St.PENDING: {St.CONFIRMED, St.CANCELLED},
    St.CONFIRMED: {St.PROCESSING, St.CANCELLED},
    St.PROCESSING: {St.READY_FOR_PICKUP, St.OUT_FOR_DELIVERY, St.CANCELLED},
    St.READY_FOR_PICKUP: {St.COMPLETED, St.CANCELLED},
    St.OUT_FOR_DELIVERY: {St.DELIVERED, St.PROCESSING},  # PROCESSING = delivery failed, goods back
    St.DELIVERED: {St.COMPLETED},
    St.COMPLETED: set(),
    St.CANCELLED: set(),
}
TIMESTAMPS = {St.CONFIRMED: "confirmed_at", St.READY_FOR_PICKUP: "ready_at", St.OUT_FOR_DELIVERY: "dispatched_at",
              St.DELIVERED: "delivered_at", St.COMPLETED: "completed_at"}


def transition_problem(order, to_status):
    """Why `order` can't move to `to_status` (None if it can)."""
    if to_status not in TRANSITIONS.get(order.status, set()):
        return f"An order that is {order.get_status_display().lower()} can't be marked {St(to_status).label.lower()}."
    if to_status == St.READY_FOR_PICKUP and order.fulfilment != F.PICKUP:
        return "Only pickup orders can be ready for pickup."
    if to_status == St.OUT_FOR_DELIVERY and order.fulfilment != F.DELIVERY:
        return "Only delivery orders can go out for delivery."
    if to_status == St.CONFIRMED and order.payment_method != PM.CASH and not order.is_paid:
        return "Confirm bank-transfer and online orders only after the payment is verified."
    if to_status == St.COMPLETED and not order.is_paid:
        return "Record or verify the payment before completing the order."
    return None


def allowed_transitions(order):
    """Status changes staff may make now (cancelling is offered separately)."""
    return [s for s in St if s != St.CANCELLED and transition_problem(order, s) is None]


@transaction.atomic
def change_status(order, to_status, user, note=""):
    if to_status == St.CANCELLED:
        return cancel_order(order, user, note)
    order = Order.objects.select_for_update().get(pk=order.pk)
    problem = transition_problem(order, to_status)
    if problem:
        raise OrderError(problem)
    old = order.status
    order.status = to_status
    fields = ["status", "updated_at"]
    if to_status in TIMESTAMPS:
        setattr(order, TIMESTAMPS[to_status], timezone.now())
        fields.append(TIMESTAMPS[to_status])
    order.save(update_fields=fields)
    OrderStatusEvent.objects.create(order=order, from_status=old, to_status=to_status, note=note.strip(), created_by=user)
    _notify_on_commit(order, "status")
    return order


CUSTOMER_CANCELLABLE = {St.PENDING}
STAFF_CANCELLABLE = {St.PENDING, St.CONFIRMED, St.PROCESSING, St.READY_FOR_PICKUP}


def customer_can_cancel(order):
    return (order.status in CUSTOMER_CANCELLABLE
            and order.payment_status in (Order.PaymentStatus.PENDING,))


@transaction.atomic
def cancel_order(order, user, reason, by_customer=False):
    """Cancel an order and put its stock back (once). Paid orders become 'refund due'."""
    if not (reason or "").strip():
        raise OrderError("Please give a reason for cancelling.")
    order = Order.objects.select_for_update().get(pk=order.pk)
    if by_customer and not customer_can_cancel(order):
        raise OrderError("This order can no longer be cancelled online. Please contact us.")
    # An in-store sale is completed at the till; it can still be voided/refunded (POS refunds).
    cancellable = STAFF_CANCELLABLE | {St.COMPLETED} if order.channel == Order.Channel.POS else STAFF_CANCELLABLE
    if order.status not in cancellable:
        raise OrderError(f"An order that is {order.get_status_display().lower()} can't be cancelled.")
    old = order.status
    now = timezone.now()
    Order.objects.filter(pk=order.pk).update(status=St.CANCELLED, cancelled_at=now, cancelled_by=user,
                                             cancel_reason=reason.strip(), updated_at=now)
    order.refresh_from_db()
    for item in order.items.select_related("variation__inventory_item"):
        already = item.stock_movements.filter(movement_type=StockMovement.Type.ORDER_CANCEL).exists()
        sold = item.stock_movements.filter(movement_type=StockMovement.Type.SALE).first()
        if sold and not already:
            record_movement(sold.item, StockMovement.Type.ORDER_CANCEL, item.quantity, user,
                            reason=f"Order {order.number} cancelled", order_item=item)
    Order.objects.filter(pk=order.pk).update(stock_restored=True)
    from apps.payments.services import close_open_payments_for_cancelled_order

    close_open_payments_for_cancelled_order(order, user)
    OrderStatusEvent.objects.create(order=order, from_status=old, to_status=St.CANCELLED, created_by=user,
                                    note=("Cancelled by customer: " if by_customer else "") + reason.strip())
    order.refresh_from_db()
    _notify_on_commit(order, "cancelled")
    return order


def new_checkout_token():
    return uuid.uuid4()


def _notify_on_commit(order, kind):
    from .notifications import notify_customer

    notify_customer(order, kind)
