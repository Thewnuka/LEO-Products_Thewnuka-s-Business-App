"""
Inventory business logic. The ONLY place stock quantities change.

Concurrency safety
------------------
record_movement() runs in a transaction and:
  1. locks the item row (SELECT ... FOR UPDATE on PostgreSQL; SQLite allows
     only one writer at a time anyway);
  2. changes the quantity with a single conditional UPDATE using F(), so a
     decrease that would go below zero affects 0 rows and is refused, even if
     another request changed the stock a moment earlier;
  3. reads the new quantity back and writes the StockMovement with the exact
     before/after values.

Receiving a purchase flips its status DRAFT -> RECEIVED with a conditional
UPDATE first; a second (or simultaneous) receive updates 0 rows and stops.
A database constraint also allows only one movement per purchase line.

Costs (Phase 08)
----------------
Each item keeps a weighted average cost per stock unit. Receiving a purchase
line updates it:  new = (stock before x old cost + line total) / (stock before + added).
If no cost was known yet, the purchase's cost becomes the item's cost (stock
already on hand is valued at it from then on; past sales are never re-costed).
The Owner can also set a cost (e.g. products made in-house). Every change is
logged in ItemCostChange.
"""
from dataclasses import dataclass
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count, F, Q, Sum
from django.utils import timezone

from .models import InventoryItem, ItemCostChange, Purchase, PurchaseLine, StockMovement, Supplier

T = StockMovement.Type
INCREASING = {T.OPENING, T.PURCHASE, T.INCREASE, T.ORDER_CANCEL}
DECREASING = {T.DECREASE, T.DAMAGE, T.EXPIRED, T.SALE}
MANUAL_TYPES = [T.INCREASE, T.DECREASE, T.DAMAGE, T.EXPIRED, T.CORRECTION, T.OTHER]


class StockError(ValidationError):
    """A stock operation that is not allowed (shown to the user as a message)."""


def money(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------
def to_stock_quantity(item, quantity, unit=None):
    """
    Convert `quantity` entered in `unit` into the item's stock unit.

    Raw materials: `unit` may be any unit of the same measurement type with a
    conversion value (e.g. g -> kg). Finished products: counted in whole
    packets; `unit` must be empty.
    """
    quantity = Decimal(quantity)
    if item.is_finished:
        if unit is not None:
            raise ValidationError(f"Finished products are counted in {item.count_label}; do not choose a unit.")
        if quantity != quantity.to_integral_value():
            raise ValidationError(f"Use whole {item.count_label} (no fractions).")
        return quantity
    stock_unit = item.stock_unit
    unit = unit or stock_unit
    factor = unit.factor_to(stock_unit)
    if factor is None:
        raise ValidationError(f"{unit.symbol} cannot be converted to {stock_unit.symbol}. "
                              f"Enter the quantity in {stock_unit.symbol}.")
    converted = quantity * factor
    if converted != converted.quantize(Decimal("0.001")):
        raise ValidationError(f"Too precise: {converted.normalize():f} {stock_unit.symbol}. "
                              f"Stock is kept to 3 decimal places of {stock_unit.symbol}.")
    return converted.quantize(Decimal("0.001"))


# ---------------------------------------------------------------------------
# The single entry point for stock changes
# ---------------------------------------------------------------------------
@transaction.atomic
def record_movement(item, movement_type, quantity, user, *, reason="", unit=None, direction=None,
                    purchase=None, purchase_line=None, order_item=None):
    """
    Apply one stock movement and return the StockMovement.

    quantity   amount entered by the user (positive), in `unit` (default: stock unit).
               For CORRECTION it is the counted, correct total.
    direction  OTHER adjustments only: "in" or "out".
    """
    quantity = Decimal(quantity)
    if movement_type not in T.values:
        raise StockError("Unknown movement type.")
    if movement_type != T.CORRECTION and quantity <= 0:
        raise StockError("Quantity must be greater than zero.")
    if movement_type == T.CORRECTION and quantity < 0:
        raise StockError("The counted quantity cannot be negative.")
    if movement_type in (T.INCREASE, T.DECREASE, T.DAMAGE, T.EXPIRED, T.CORRECTION, T.OTHER) and not reason.strip():
        raise StockError("Please give a reason for this adjustment.")
    amount = to_stock_quantity(item, quantity, unit)

    locked = InventoryItem.objects.select_for_update().get(pk=item.pk)
    # Restocking a cancelled order is always allowed: the goods exist even if the item was deactivated.
    if not locked.is_active and movement_type != T.ORDER_CANCEL:
        raise StockError("This item is inactive. Activate it before changing its stock.")

    if movement_type == T.OPENING:
        if locked.movements.exists():
            raise StockError("Opening stock can only be entered before any other stock movement.")
        delta = amount
    elif movement_type in INCREASING:
        delta = amount
    elif movement_type in DECREASING:
        delta = -amount
    elif movement_type == T.CORRECTION:
        delta = amount - locked.quantity
        if delta == 0:
            raise StockError("The counted quantity equals the current stock; nothing to correct.")
    else:  # OTHER
        if direction not in ("in", "out"):
            raise StockError("Choose whether this adjustment adds or removes stock.")
        delta = amount if direction == "in" else -amount

    now = timezone.now()
    rows = InventoryItem.objects.filter(pk=locked.pk)
    if movement_type == T.CORRECTION:
        rows = rows.filter(quantity=locked.quantity)  # stock changed meanwhile? -> refuse, user recounts
    elif delta < 0 and not locked.allow_negative:
        rows = rows.filter(quantity__gte=-delta)
    updated = rows.update(quantity=F("quantity") + delta, last_movement_at=now, updated_at=now)
    if not updated:
        if movement_type == T.CORRECTION:
            raise StockError("The stock changed while you were correcting it. Please check the new figure and try again.")
        current = InventoryItem.objects.values_list("quantity", flat=True).get(pk=locked.pk)
        raise StockError(f"Not enough stock: {locked.format_qty(current)} available, "
                         f"{locked.format_qty(-delta)} requested. Stock cannot go below zero.")

    after = InventoryItem.objects.values_list("quantity", flat=True).get(pk=locked.pk)
    entered_unit = None if locked.is_finished else (unit or locked.stock_unit)
    movement = StockMovement.objects.create(
        item=locked, movement_type=movement_type, quantity_change=delta,
        quantity_before=after - delta, quantity_after=after,
        entered_quantity=quantity, entered_unit=entered_unit,
        reason=reason.strip(), purchase=purchase, purchase_line=purchase_line, order_item=order_item, created_by=user,
    )
    item.quantity, item.last_movement_at = after, now  # keep the caller's object current
    if delta < 0 and locked.is_active:
        from apps.notifications.events import stock_crossed

        stock_crossed(locked, movement)
    return movement


@dataclass
class AdjustmentPreview:
    item: InventoryItem
    movement_type: str
    before: Decimal
    after: Decimal
    change: Decimal

    @property
    def would_go_negative(self):
        return self.after < 0 and not self.item.allow_negative


def preview_movement(item, movement_type, quantity, unit=None, direction=None):
    """What a movement would do, for the confirmation page (no changes are saved)."""
    amount = to_stock_quantity(item, quantity, unit)
    before = item.quantity
    if movement_type == T.CORRECTION:
        after = amount
    elif movement_type in INCREASING or (movement_type == T.OTHER and direction == "in"):
        after = before + amount
    else:
        after = before - amount
    return AdjustmentPreview(item, movement_type, before, after, after - before)


# ---------------------------------------------------------------------------
# Inventory items
# ---------------------------------------------------------------------------
@transaction.atomic
def create_item_with_opening_stock(item, opening_quantity, user, unit=None):
    """Save a new item and record its opening stock (which may be 0)."""
    item.created_by = user
    item.full_clean()
    item.save()
    opening_quantity = Decimal(opening_quantity or 0)
    if opening_quantity > 0:
        record_movement(item, T.OPENING, opening_quantity, user, unit=unit, reason="Opening stock")
    return item


# ---------------------------------------------------------------------------
# Purchases
# ---------------------------------------------------------------------------
def next_purchase_reference(today=None):
    year = (today or timezone.localdate()).year
    prefix = f"PO-{year}-"
    last = (Purchase.objects.filter(reference__startswith=prefix).order_by("-reference")
            .values_list("reference", flat=True).first())
    number = int(last.rsplit("-", 1)[1]) + 1 if last else 1
    return f"{prefix}{number:04d}"


def save_new_purchase(purchase, user):
    """Assign a reference (PO-YYYY-NNNN) and save, retrying if two users save at once."""
    purchase.created_by = user
    for _ in range(5):
        purchase.reference = next_purchase_reference(purchase.purchase_date)
        try:
            with transaction.atomic():
                purchase.save()
            return purchase
        except IntegrityError:
            purchase.pk = None
    raise StockError("Could not create a purchase reference. Please try again.")


@transaction.atomic
def receive_purchase(purchase, user):
    """
    Add every line of a DRAFT purchase to stock, exactly once.

    The status change is a conditional UPDATE (only from DRAFT), so a second
    click, a second browser tab or two users at once cannot receive it twice.
    """
    lines = list(purchase.lines.select_related("item", "unit", "item__stock_unit", "item__variation__product"))
    if not lines:
        raise StockError("Add at least one item before receiving this purchase.")
    inactive = [line.item.display_name for line in lines if not line.item.is_active]
    if inactive:
        raise StockError("These items are inactive: " + ", ".join(inactive) + ". Activate them first.")

    now = timezone.now()
    claimed = Purchase.objects.filter(pk=purchase.pk, status=Purchase.Status.DRAFT).update(
        status=Purchase.Status.RECEIVED, received_at=now, received_by=user, updated_at=now)
    if not claimed:
        current = Purchase.objects.values_list("status", flat=True).get(pk=purchase.pk)
        raise StockError(f"This purchase is already {Purchase.Status(current).label.lower()}; stock was not changed again.")

    for line in lines:
        movement = record_movement(line.item, T.PURCHASE, line.quantity, user, unit=line.unit,
                                   reason=f"Purchase {purchase.reference}", purchase=purchase, purchase_line=line)
        update_average_cost(line, movement, user)
    purchase.refresh_from_db()
    from apps.notifications.events import purchase_received

    purchase_received(purchase, user)
    return purchase


# ---------------------------------------------------------------------------
# Costs
# ---------------------------------------------------------------------------
COST_PLACES = Decimal("0.0001")


def update_average_cost(line, movement, user):
    """Weighted average cost after receiving one purchase line (called inside receive_purchase)."""
    added = movement.quantity_change
    if added <= 0:
        return None
    item = InventoryItem.objects.select_for_update().get(pk=line.item_id)
    old_cost, before = item.average_cost, movement.quantity_before
    line_cost = Decimal(line.line_total)
    if old_cost is None or before <= 0:
        # No known cost for what is on hand (or nothing on hand): this purchase sets the cost.
        new_cost = line_cost / added
    else:
        new_cost = (before * old_cost + line_cost) / (before + added)
    new_cost = new_cost.quantize(COST_PLACES, rounding=ROUND_HALF_UP)
    now = timezone.now()
    InventoryItem.objects.filter(pk=item.pk).update(average_cost=new_cost, cost_updated_at=now)
    return ItemCostChange.objects.create(item=item, source=ItemCostChange.Source.PURCHASE, old_cost=old_cost,
                                         new_cost=new_cost, quantity_before=before, quantity_added=added,
                                         purchase_line=line, changed_by=user,
                                         reason=f"Purchase {line.purchase.reference}")


@transaction.atomic
def set_item_cost(item, cost, user, reason):
    """The Owner sets an item's cost per stock unit (from now on; past sales keep their recorded cost)."""
    if not (reason or "").strip():
        raise StockError("Please explain where this cost comes from.")
    try:
        cost = Decimal(str(cost)).quantize(COST_PLACES, rounding=ROUND_HALF_UP)
    except Exception:
        raise StockError("Enter a valid cost.")
    if cost < 0:
        raise StockError("The cost can't be negative.")
    item = InventoryItem.objects.select_for_update().get(pk=item.pk)
    if item.average_cost == cost:
        raise StockError("That is already the item's cost.")
    change = ItemCostChange.objects.create(item=item, source=ItemCostChange.Source.MANUAL, old_cost=item.average_cost,
                                           new_cost=cost, quantity_before=item.quantity, changed_by=user,
                                           reason=reason.strip()[:200])
    InventoryItem.objects.filter(pk=item.pk).update(average_cost=cost, cost_updated_at=timezone.now())
    return change


@transaction.atomic
def cancel_purchase(purchase, user, reason):
    """Cancel a DRAFT purchase. Received purchases cannot be cancelled (stock already moved)."""
    if not (reason or "").strip():
        raise StockError("Please give a reason for cancelling.")
    now = timezone.now()
    done = Purchase.objects.filter(pk=purchase.pk, status=Purchase.Status.DRAFT).update(
        status=Purchase.Status.CANCELLED, cancelled_at=now, cancelled_by=user, cancel_reason=reason.strip(), updated_at=now)
    if not done:
        raise StockError("Only draft purchases can be cancelled. To undo received stock, record a stock decrease with a reason.")
    purchase.refresh_from_db()
    return purchase


# ---------------------------------------------------------------------------
# Search & dashboard
# ---------------------------------------------------------------------------
ITEM_SORTS = {
    "name": ("Name (A–Z)", ["kind", "name", "variation__product__name", "variation__quantity"]),
    "qty": ("Lowest quantity", ["quantity", "pk"]),
    "-qty": ("Highest quantity", ["-quantity", "pk"]),
    "-updated": ("Recently changed", ["-last_movement_at", "-pk"]),
}


def filter_items(params):
    qs = (InventoryItem.objects.select_related("stock_unit", "category", "variation__product__category",
                                               "variation__product__subcategory", "variation__unit")
          .with_stock_status())
    q = (params.get("q") or "").strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(variation__product__name__icontains=q)
                       | Q(variation__sku__icontains=q) | Q(variation__name__icontains=q))
    if params.get("kind"):
        qs = qs.filter(kind=params["kind"])
    if params.get("state"):
        qs = qs.filter(stock_state=params["state"]) if params["state"] != "ATTENTION" else qs.needs_attention()
    if params.get("category"):
        c = params["category"]
        qs = qs.filter(Q(category=c) | Q(category__parent=c) | Q(variation__product__category=c)
                       | Q(variation__product__subcategory=c))
    unit = params.get("unit")
    if unit == "packets":
        qs = qs.filter(kind=InventoryItem.Kind.FINISHED_GOOD)
    elif unit:
        qs = qs.filter(stock_unit=unit)
    if params.get("active") == "yes":
        qs = qs.filter(is_active=True)
    elif params.get("active") == "no":
        qs = qs.filter(is_active=False)
    sort = params.get("sort") if params.get("sort") in ITEM_SORTS else "name"
    return qs.order_by(*ITEM_SORTS[sort][1])


def filter_purchases(params):
    qs = Purchase.objects.select_related("supplier", "created_by").annotate(line_count=Count("lines"))
    q = (params.get("q") or "").strip()
    if q:
        qs = qs.filter(Q(reference__icontains=q) | Q(invoice_number__icontains=q))
    if params.get("supplier"):
        qs = qs.filter(supplier=params["supplier"])
    if params.get("status"):
        qs = qs.filter(status=params["status"])
    if params.get("date_from"):
        qs = qs.filter(purchase_date__gte=params["date_from"])
    if params.get("date_to"):
        qs = qs.filter(purchase_date__lte=params["date_to"])
    return qs.order_by("-purchase_date", "-pk")


def inventory_stats():
    items = InventoryItem.objects.filter(is_active=True)
    since = timezone.now() - timedelta(days=30)
    adjustments = (StockMovement.objects.filter(created_at__gte=since).exclude(movement_type__in=[T.OPENING, T.PURCHASE, T.SALE, T.ORDER_CANCEL])
                   .values("movement_type").annotate(count=Count("id")).order_by("movement_type"))
    labels = dict(T.choices)
    from apps.catalog.models import ProductVariation

    return {
        "total_items": items.count(),
        "raw_items": items.filter(kind=InventoryItem.Kind.RAW_MATERIAL).count(),
        "finished_items": items.filter(kind=InventoryItem.Kind.FINISHED_GOOD).count(),
        "active_suppliers": Supplier.objects.filter(is_active=True).count(),
        "low_stock": items.filter(quantity__gt=0, quantity__lte=F("reorder_level")).count(),
        "out_of_stock": items.filter(quantity__lte=0).count(),
        "draft_purchases": Purchase.objects.filter(status=Purchase.Status.DRAFT).count(),
        "untracked_variations": ProductVariation.objects.filter(inventory_item__isnull=True, is_active=True).count(),
        "adjustments_30d": [{"type": labels[a["movement_type"]], "code": a["movement_type"], "count": a["count"]} for a in adjustments],
        "movements_30d": StockMovement.objects.filter(created_at__gte=since).count(),
        "received_30d_total": Purchase.objects.filter(status=Purchase.Status.RECEIVED, received_at__gte=since)
                                       .aggregate(total=Sum("total"))["total"] or Decimal("0.00"),
    }
