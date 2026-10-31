"""
Point-of-sale logic.

A POS sale is an orders.Order with channel=POS. It reuses the order lines,
orders.services.add_items_and_deduct_stock (one SALE ledger movement per line,
never below zero) and payments.Payment, all inside ONE transaction:

  CASH           paid at once: the payment is PAID, with the cash handed over and the change;
                 the sale is COMPLETED.
  BANK_TRANSFER  the cashier records the customer's transfer reference; the payment stays
                 PENDING_VERIFICATION and the sale PENDING until a Manager/Owner approves it
                 (payments.services.review_bank_transfer completes the sale). It is never
                 marked paid at the till.

Every sale needs the cashier's OPEN shift. The browser's checkout token makes a
sale idempotent: submitting the same sale twice returns the first one.

Expected cash in a drawer = opening cash + cash sales + cash added - cash taken out - cash refunds.
"""
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count, Sum
from django.utils import timezone

from apps.accounts.roles import Capability, has_capability
from apps.catalog.models import ProductVariation
from apps.notifications import events
from apps.orders import services as orders
from apps.orders.models import Order, OrderStatusEvent
from apps.payments import services as payments
from apps.payments.models import Payment
from apps.shop import services as shop

from .models import CashierShift, CashMovement, PosSettings, ReceiptPrint

CENT = Decimal("0.01")
ZERO = Decimal("0.00")
MAX_LINE_QUANTITY = 999
PM = Order.PaymentMethod
PAY = Payment.Status


class PosError(ValidationError):
    """A POS action that is not allowed (shown to the cashier)."""


def _money(value):
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Shifts and cash drawer
# ---------------------------------------------------------------------------
def current_shift(user):
    return CashierShift.objects.filter(cashier=user, status=CashierShift.Status.OPEN).first()


def open_shift(cashier, opening_cash, note=""):
    opening_cash = _money(opening_cash)
    if opening_cash < 0:
        raise PosError("Opening cash can't be negative.")
    try:
        with transaction.atomic():
            return CashierShift.objects.create(cashier=cashier, opening_cash=opening_cash, opening_note=note.strip())
    except IntegrityError:
        raise PosError("You already have an open shift. Close it before opening a new one.")


@dataclass
class ShiftSummary:
    opening_cash: Decimal
    sales_count: int
    sales_total: Decimal
    discounts: Decimal
    cash_sales: Decimal
    bank_paid: Decimal
    bank_pending: Decimal
    cash_in: Decimal
    cash_out: Decimal
    cash_refunds: Decimal
    voided_count: int

    @property
    def expected_cash(self):
        return self.opening_cash + self.cash_sales + self.cash_in - self.cash_out - self.cash_refunds


def shift_summary(shift):
    sales = Order.objects.filter(shift=shift)
    kept = sales.exclude(status=Order.Status.CANCELLED)
    agg = kept.aggregate(n=Count("pk"), total=Sum("total"), discounts=Sum("discount_amount"))
    pays = Payment.objects.filter(order__shift=shift)
    # Cash received counts even if the sale was refunded later: the refund is a separate drawer movement.
    cash_sales = pays.filter(method=PM.CASH, status__in=[PAY.PAID, PAY.REFUNDED]).aggregate(s=Sum("amount"))["s"]
    bank_paid = pays.filter(method=PM.BANK_TRANSFER, status=PAY.PAID).aggregate(s=Sum("amount"))["s"]
    bank_pending = pays.filter(method=PM.BANK_TRANSFER, status=PAY.PENDING_VERIFICATION).aggregate(s=Sum("amount"))["s"]
    moves = {row["kind"]: row["s"] for row in shift.cash_movements.values("kind").annotate(s=Sum("amount"))}
    return ShiftSummary(
        opening_cash=shift.opening_cash, sales_count=agg["n"], sales_total=agg["total"] or ZERO,
        discounts=agg["discounts"] or ZERO, cash_sales=cash_sales or ZERO, bank_paid=bank_paid or ZERO,
        bank_pending=bank_pending or ZERO, cash_in=moves.get(CashMovement.Kind.CASH_IN) or ZERO,
        cash_out=moves.get(CashMovement.Kind.CASH_OUT) or ZERO,
        cash_refunds=moves.get(CashMovement.Kind.REFUND) or ZERO,
        voided_count=sales.filter(status=Order.Status.CANCELLED).count(),
    )


def can_manage_shift(user, shift):
    return shift.cashier_id == user.pk or has_capability(user, Capability.MANAGE_SHIFTS)


@transaction.atomic
def add_cash_movement(shift, user, kind, amount, reason):
    """Cash put into (CASH_IN) or taken out of (CASH_OUT) an open drawer, with a reason."""
    if kind not in (CashMovement.Kind.CASH_IN, CashMovement.Kind.CASH_OUT):
        raise PosError("Choose cash in or cash out.")
    if not reason.strip():
        raise PosError("Please give a reason.")
    amount = _money(amount)
    if amount <= 0:
        raise PosError("The amount must be greater than zero.")
    shift = CashierShift.objects.select_for_update().get(pk=shift.pk)
    if not can_manage_shift(user, shift):
        raise PosError("You can only record cash for your own shift.")
    if not shift.is_open:
        raise PosError("This shift is closed. Closed shifts can't be changed.")
    if kind == CashMovement.Kind.CASH_OUT:
        expected = shift_summary(shift).expected_cash
        if amount > expected:
            raise PosError(f"The drawer should only hold LKR {expected:,.2f}; you can't take out more than that.")
    return CashMovement.objects.create(shift=shift, kind=kind, amount=amount, reason=reason.strip(), created_by=user)


@transaction.atomic
def close_shift(shift, user, counted_cash, note=""):
    """Close an open shift with the counted cash. Expected cash and the difference are fixed from now on."""
    counted_cash = _money(counted_cash)
    if counted_cash < 0:
        raise PosError("Counted cash can't be negative.")
    shift = CashierShift.objects.select_for_update().get(pk=shift.pk)
    if not can_manage_shift(user, shift):
        raise PosError("You can only close your own shift.")
    if not shift.is_open:
        raise PosError("This shift is already closed.")
    expected = shift_summary(shift).expected_cash
    difference = counted_cash - expected
    if difference and not note.strip():
        raise PosError(f"The count is LKR {difference:+,.2f} different from the expected LKR {expected:,.2f}. "
                       "Please explain the difference in the note.")
    now = timezone.now()
    CashierShift.objects.filter(pk=shift.pk, status=CashierShift.Status.OPEN).update(
        status=CashierShift.Status.CLOSED, closed_at=now, closed_by=user, expected_cash=expected,
        counted_cash=counted_cash, difference=difference, closing_note=note.strip(), updated_at=now)
    shift.refresh_from_db()
    events.shift_closed_with_difference(shift, user)
    return shift


# ---------------------------------------------------------------------------
# Discounts
# ---------------------------------------------------------------------------
def discount_limit(user, config=None):
    """Largest discount (% of the sale) this user may give or approve."""
    config = config or PosSettings.load()
    if has_capability(user, Capability.UNLIMITED_DISCOUNTS):
        return Decimal("100")
    if has_capability(user, Capability.APPROVE_DISCOUNTS):
        return config.manager_discount_limit
    if has_capability(user, Capability.PROCESS_SALES):
        return config.cashier_discount_limit
    return ZERO


def discount_amount(subtotal, discount_type, value):
    """LKR discount for the sale. Raises PosError for invalid values."""
    if not discount_type:
        return ZERO
    try:
        value = Decimal(str(value))
    except Exception:
        raise PosError("Enter a valid discount.")
    if value <= 0:
        raise PosError("The discount must be greater than zero.")
    if discount_type == Order.DiscountType.PERCENT:
        if value > 100:
            raise PosError("A percentage discount can't be more than 100%.")
        amount = _money(subtotal * value / 100)
    elif discount_type == Order.DiscountType.FIXED:
        amount = _money(value)
    else:
        raise PosError("Unknown discount type.")
    if amount > subtotal:
        raise PosError("The discount can't be more than the sale amount.")
    return amount


def discount_percent(subtotal, amount):
    return (amount * 100 / subtotal).quantize(CENT, rounding=ROUND_HALF_UP) if subtotal else ZERO


def needs_approval(cashier, subtotal, amount, config=None):
    return amount > 0 and discount_percent(subtotal, amount) > discount_limit(cashier, config)


# ---------------------------------------------------------------------------
# Sales
# ---------------------------------------------------------------------------
def sellable_variations():
    """Variations the till can sell now: same rules as the online shop (active, in stock)."""
    qs = (ProductVariation.objects.filter(is_active=True, inventory_item__isnull=False)
          .select_related("product__category", "product__subcategory", "unit", "inventory_item")
          .order_by("product__category__name", "product__name", "sort_order", "pk"))
    return [v for v in qs if shop.available_stock(v) > 0]


def _resolve_lines(raw_lines):
    """[(variation_id, qty), ...] -> [(variation, qty, unit_price)] with stock checked."""
    merged = {}
    for variation_id, qty in raw_lines:
        try:
            variation_id, qty = int(variation_id), int(qty)
        except (TypeError, ValueError):
            raise PosError("The cart contains an invalid item.")
        if qty < 1 or qty > MAX_LINE_QUANTITY:
            raise PosError(f"Quantities must be between 1 and {MAX_LINE_QUANTITY}.")
        merged[variation_id] = merged.get(variation_id, 0) + qty
    if not merged:
        raise PosError("The cart is empty.")
    variations = {v.pk: v for v in ProductVariation.objects.filter(pk__in=merged)
                  .select_related("product__category", "product__subcategory", "unit", "inventory_item")}
    lines = []
    for variation_id, qty in merged.items():
        v = variations.get(variation_id)
        if v is None:
            raise PosError("An item in the cart no longer exists.")
        available = shop.available_stock(v)
        name = f"{v.product.name} ({v.display_name})"
        if available <= 0:
            raise PosError(f"{name} is not available for sale.")
        if qty > available:
            raise PosError(f"Only {available} of {name} in stock.")
        lines.append((v, qty, v.selling_price))
    return lines


def create_sale(*, cashier, lines, payment_method, token, cash_tendered=None, bank_reference="",
                discount_type="", discount_value=None, discount_reason="", approver=None,
                customer_name="", customer_phone="", expected_total=None):
    """
    Record an in-store sale. Returns (order, created). Sending the same `token`
    again returns the first sale instead of selling (and deducting stock) twice.
    """
    for attempt in range(3):
        existing = Order.objects.filter(checkout_token=token).first()
        if existing:
            if existing.cashier_id != cashier.pk:
                raise PosError("This sale belongs to another till session. Reload the POS.")
            return existing, False
        try:
            with transaction.atomic():
                return _create_sale(cashier, lines, payment_method, token, cash_tendered, bank_reference,
                                    discount_type, discount_value, discount_reason, approver,
                                    customer_name, customer_phone, expected_total), True
        except IntegrityError:
            # Same token sent twice at once (the loop returns the first sale) or a number clash (retry).
            if attempt == 2:
                raise


def _create_sale(cashier, raw_lines, payment_method, token, cash_tendered, bank_reference,
                 discount_type, discount_value, discount_reason, approver, customer_name, customer_phone,
                 expected_total):
    if not has_capability(cashier, Capability.PROCESS_SALES):
        raise PosError("You are not allowed to make sales.")
    shift = CashierShift.objects.select_for_update().filter(cashier=cashier, status=CashierShift.Status.OPEN).first()
    if shift is None:
        raise PosError("Open your shift before making sales.")
    if payment_method not in (PM.CASH, PM.BANK_TRANSFER):
        raise PosError("Choose cash or bank transfer.")

    lines = _resolve_lines(raw_lines)
    subtotal = sum((price * qty for _v, qty, price in lines), ZERO)
    config = PosSettings.load()
    amount = discount_amount(subtotal, discount_type, discount_value)
    approved_by = None
    if amount:
        if not (discount_reason or "").strip():
            raise PosError("Please give a reason for the discount.")
        percent = discount_percent(subtotal, amount)
        if percent > discount_limit(cashier, config):
            if approver is None:
                raise PosError(f"A {percent}% discount needs approval from a Manager or the Owner.", code="needs_approval")
            if approver.pk == cashier.pk or not has_capability(approver, Capability.APPROVE_DISCOUNTS):
                raise PosError("The approver is not allowed to approve discounts.")
            if percent > discount_limit(approver, config):
                raise PosError(f"{approver.get_full_name() or approver.username} can approve up to "
                               f"{discount_limit(approver, config)}%; this discount is {percent}%.")
            approved_by = approver
    total = subtotal - amount
    if expected_total is not None and _money(expected_total) != total:
        raise PosError(f"Prices changed since the POS screen was loaded. The correct total is LKR {total:,.2f}. "
                       "Please check the cart and try again.", code="total_changed")

    change = None
    if payment_method == PM.CASH:
        if cash_tendered in (None, ""):
            raise PosError("Enter the cash received.")
        cash_tendered = _money(cash_tendered)
        if cash_tendered < total:
            raise PosError(f"Cash received (LKR {cash_tendered:,.2f}) is less than the total (LKR {total:,.2f}).")
        change = cash_tendered - total
    else:
        cash_tendered = None
        bank_reference = (bank_reference or "").strip()
        if not bank_reference:
            raise PosError("Enter the bank transfer reference.")

    now = timezone.now()
    paid_now = payment_method == PM.CASH
    order = Order.objects.create(
        number=orders.next_order_number("POS"), channel=Order.Channel.POS, cashier=cashier, shift=shift,
        checkout_token=token, full_name=(customer_name or "").strip()[:150] or "Walk-in customer",
        phone=(customer_phone or "").strip()[:20], fulfilment=Order.Fulfilment.IN_STORE,
        subtotal=subtotal, discount_type=discount_type if amount else "", discount_value=_money(discount_value) if amount else ZERO,
        discount_amount=amount, discount_reason=(discount_reason or "").strip()[:200] if amount else "",
        discount_applied_by=cashier if amount else None, discount_approved_by=approved_by,
        delivery_fee=ZERO, total=total, payment_method=payment_method,
        status=Order.Status.COMPLETED if paid_now else Order.Status.PENDING,
        completed_at=now if paid_now else None,
    )
    orders.add_items_and_deduct_stock(order, lines, cashier, reason=f"POS sale {order.number}")
    if paid_now:
        payment = payments.create_payment(order, status=PAY.PAID, verified_by=cashier, verified_at=now, paid_at=now,
                                          cash_tendered=cash_tendered, change_given=change,
                                          verification_note="Cash received at the till")
        payments.log(payment, "cash_received", cashier, amount=str(payment.amount), tendered=str(cash_tendered))
    else:
        payment = payments.create_payment(order, status=PAY.PENDING_VERIFICATION, bank_reference=bank_reference,
                                          submitted_at=now)
        payments.log(payment, "bank_transfer_submitted", cashier, reference=bank_reference)
        events.transfer_to_verify(payment)
    payments.sync_order_payment_status(order)
    OrderStatusEvent.objects.create(
        order=order, to_status=order.status, created_by=cashier,
        note="In-store sale" if paid_now else "In-store sale, waiting for bank transfer verification")
    return order


# ---------------------------------------------------------------------------
# Refunds / voids
# ---------------------------------------------------------------------------
def refund_sale(order, user, reason, drawer_shift=None):
    """
    Void an in-store sale: stock goes back once (orders.cancel_order) and a paid payment
    is marked refunded once (payments.record_refund). Cash refunds are paid out of an
    OPEN drawer (`drawer_shift`) and recorded there.
    """
    if not has_capability(user, Capability.REFUND_POS_SALES):
        raise PosError("You are not allowed to refund sales.")
    if order.channel != Order.Channel.POS:
        raise PosError("Only in-store sales are refunded here.")
    if not (reason or "").strip():
        raise PosError("Please give a reason for the refund.")
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order.pk)
        if order.status == Order.Status.CANCELLED:
            raise PosError("This sale has already been voided.")
        paid = Payment.objects.filter(order=order, status=PAY.PAID).first()
        cash_refund = paid is not None and paid.method == PM.CASH and paid.amount > 0
        if cash_refund:
            if drawer_shift is None:
                raise PosError("Choose the open till the cash refund is paid from.")
            drawer_shift = CashierShift.objects.select_for_update().get(pk=drawer_shift.pk)
            if not drawer_shift.is_open:
                raise PosError("That shift is closed. Choose an open till.")
            available = shift_summary(drawer_shift).expected_cash
            if paid.amount > available:
                raise PosError(f"That drawer should only hold LKR {available:,.2f}; it can't pay a "
                               f"LKR {paid.amount:,.2f} refund.")
        orders.cancel_order(order, user, f"Refunded at the till: {reason.strip()}")
        if paid:
            payments.record_refund(paid, user, reason.strip())
        if cash_refund:
            CashMovement.objects.create(shift=drawer_shift, kind=CashMovement.Kind.REFUND, amount=paid.amount,
                                        reason=f"Refund {order.number}: {reason.strip()}"[:200], order=order,
                                        created_by=user)
        events.pos_sale_refunded(order, user)
    order.refresh_from_db()
    return order


# ---------------------------------------------------------------------------
# Access, receipts and summaries
# ---------------------------------------------------------------------------
def can_view_sale(user, order):
    if order.channel != Order.Channel.POS:
        return False
    if has_capability(user, Capability.VIEW_POS_SALES):
        return True
    return has_capability(user, Capability.VIEW_OWN_TRANSACTIONS) and order.cashier_id == user.pk


def visible_sales(user):
    sales = Order.objects.filter(channel=Order.Channel.POS)
    if has_capability(user, Capability.VIEW_POS_SALES):
        return sales
    if has_capability(user, Capability.VIEW_OWN_TRANSACTIONS):
        return sales.filter(cashier=user)
    return sales.none()


def visible_shifts(user):
    if has_capability(user, Capability.MANAGE_SHIFTS):
        return CashierShift.objects.all()
    if has_capability(user, Capability.PROCESS_SALES):
        return CashierShift.objects.filter(cashier=user)
    return CashierShift.objects.none()


def record_reprint(order, user):
    return ReceiptPrint.objects.create(order=order, printed_by=user)


def today_summary(user):
    """Today's POS figures for the dashboard: everything for Manager/Owner, own sales for a cashier."""
    today = timezone.localdate()
    sales = visible_sales(user).filter(created_at__date=today)
    kept = sales.exclude(status=Order.Status.CANCELLED)
    pays = Payment.objects.filter(order__in=sales)
    shifts = visible_shifts(user).filter(status=CashierShift.Status.OPEN).select_related("cashier")
    open_shifts = [(s, shift_summary(s)) for s in shifts]
    return {
        "sales_total": kept.aggregate(s=Sum("total"))["s"] or ZERO,
        "sales_count": kept.count(),
        "cash_sales": pays.filter(method=PM.CASH, status__in=[PAY.PAID, PAY.REFUNDED]).aggregate(s=Sum("amount"))["s"] or ZERO,
        "bank_sales": pays.filter(method=PM.BANK_TRANSFER, status=PAY.PAID).aggregate(s=Sum("amount"))["s"] or ZERO,
        "bank_pending": pays.filter(method=PM.BANK_TRANSFER, status=PAY.PENDING_VERIFICATION).count(),
        "voided": sales.filter(status=Order.Status.CANCELLED).count(),
        "open_shifts": open_shifts,
        "drawer_total": sum((summary.expected_cash for _s, summary in open_shifts), ZERO),
        "all_tills": has_capability(user, Capability.VIEW_POS_SALES),
    }


def pending_transfers(user):
    return visible_sales(user).filter(payment_status=Order.PaymentStatus.PENDING_VERIFICATION)

