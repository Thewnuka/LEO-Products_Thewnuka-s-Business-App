from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.catalog.models import MeasurementType, ProductVariation
from apps.inventory.models import InventoryItem, StockMovement
from apps.inventory.services import record_movement, to_stock_quantity

from .helpers import D, InventoryTestCase, finished_item, raw_item

T = StockMovement.Type


class OpeningStockTests(InventoryTestCase):
    def test_opening_stock_creates_quantity_and_ledger_entry(self):
        self.assertEqual(self.raw.quantity, D("20"))
        self.assertEqual(self.raw.quantity_display, "20kg")
        self.assertEqual(self.packets.quantity_display, "35 packets")
        m = self.raw.movements.get()
        self.assertEqual((m.movement_type, m.quantity_before, m.quantity_change, m.quantity_after),
                         (T.OPENING, D("0"), D("20"), D("20")))
        self.assertEqual(m.created_by, self.owner)

    def test_zero_opening_stock_records_no_movement(self):
        item = finished_item(self.v400, self.manager, opening="0")
        self.assertEqual(item.quantity, 0)
        self.assertFalse(item.movements.exists())

    def test_opening_stock_only_once(self):
        with self.assertRaises(ValidationError):
            record_movement(self.raw, T.OPENING, "5", self.owner)
        self.assertEqual(self.raw.movements.filter(movement_type=T.OPENING).count(), 1)


class AdjustmentTests(InventoryTestCase):
    def test_increase_and_decrease(self):
        record_movement(self.packets, T.INCREASE, "5", self.manager, reason="Found extra carton")
        record_movement(self.packets, T.DECREASE, "3", self.manager, reason="Samples")
        record_movement(self.packets, T.DAMAGE, "2", self.manager, reason="Torn packets")
        record_movement(self.packets, T.EXPIRED, "1", self.manager, reason="Past best-before")
        self.packets.refresh_from_db()
        self.assertEqual(self.packets.quantity, D("34"))
        changes = list(self.packets.movements.order_by("pk").values_list("movement_type", "quantity_change", "quantity_after"))
        self.assertEqual(changes[1:], [(T.INCREASE, D(5), D(40)), (T.DECREASE, D(-3), D(37)),
                                       (T.DAMAGE, D(-2), D(35)), (T.EXPIRED, D(-1), D(34))])

    def test_correction_sets_counted_total(self):
        m = record_movement(self.packets, T.CORRECTION, "31", self.owner, reason="Monthly count")
        self.assertEqual((m.quantity_before, m.quantity_change, m.quantity_after), (D(35), D(-4), D(31)))
        with self.assertRaises(ValidationError):
            record_movement(self.packets, T.CORRECTION, "31", self.owner, reason="Same again")

    def test_other_adjustment_needs_direction(self):
        with self.assertRaises(ValidationError):
            record_movement(self.packets, T.OTHER, "1", self.owner, reason="?")
        record_movement(self.packets, T.OTHER, "1", self.owner, reason="Returned by shop", direction="in")
        self.packets.refresh_from_db()
        self.assertEqual(self.packets.quantity, D(36))

    def test_reason_required_for_manual_adjustments(self):
        for mtype in (T.INCREASE, T.DECREASE, T.DAMAGE, T.EXPIRED, T.CORRECTION):
            with self.subTest(mtype), self.assertRaises(ValidationError):
                record_movement(self.packets, mtype, "1", self.owner, reason="   ")

    def test_quantity_must_be_positive(self):
        for value in ("0", "-5"):
            with self.subTest(value), self.assertRaises(ValidationError):
                record_movement(self.packets, T.INCREASE, value, self.owner, reason="x")

    def test_inactive_item_cannot_move(self):
        self.packets.is_active = False
        self.packets.save()
        with self.assertRaises(ValidationError):
            record_movement(self.packets, T.INCREASE, "1", self.owner, reason="x")


class NegativeStockTests(InventoryTestCase):
    def test_decrease_below_zero_is_refused_and_nothing_recorded(self):
        before = StockMovement.objects.count()
        with self.assertRaises(ValidationError) as ctx:
            record_movement(self.packets, T.DECREASE, "36", self.owner, reason="Too many")
        self.assertIn("Not enough stock", str(ctx.exception))
        self.packets.refresh_from_db()
        self.assertEqual(self.packets.quantity, D(35))
        self.assertEqual(StockMovement.objects.count(), before)

    def test_database_constraint_also_blocks_negative(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            InventoryItem.objects.filter(pk=self.packets.pk).update(quantity=D("-1"))

    def test_owner_configured_negative_stock(self):
        self.packets.allow_negative = True
        self.packets.save()
        record_movement(self.packets, T.DECREASE, "40", self.owner, reason="Pre-sold, stock arriving")
        self.packets.refresh_from_db()
        self.assertEqual(self.packets.quantity, D(-5))


class UnitTests(InventoryTestCase):
    def test_grams_convert_to_kilograms(self):
        m = record_movement(self.raw, T.DECREASE, "1500", self.owner, unit=self.g, reason="Packed into 200g packets")
        self.raw.refresh_from_db()
        self.assertEqual(self.raw.quantity, D("18.5"))
        self.assertEqual((m.entered_quantity, m.entered_unit, m.quantity_change), (D("1500"), self.g, D("-1.5")))

    def test_incompatible_unit_rejected(self):
        with self.assertRaises(ValidationError):
            to_stock_quantity(self.raw, D("5"), self.bags)

    def test_too_precise_conversion_rejected(self):
        with self.assertRaises(ValidationError):
            to_stock_quantity(self.raw, D("0.5"), self.g)  # 0.0005 kg

    def test_finished_goods_whole_packets_only(self):
        with self.assertRaises(ValidationError):
            to_stock_quantity(self.packets, D("2.5"))
        with self.assertRaises(ValidationError):
            to_stock_quantity(self.packets, D("2"), self.g)  # no unit for packets

    def test_raw_kg_and_packets_are_separate_stock(self):
        record_movement(self.raw, T.INCREASE, "1", self.owner, reason="Delivery")
        self.packets.refresh_from_db()
        self.assertEqual(self.packets.quantity, D(35))  # 1 kg of loose tea is not a packet


class LedgerTests(InventoryTestCase):
    def test_movements_cannot_be_edited_or_deleted(self):
        m = self.raw.movements.get()
        m.reason = "changed"
        with self.assertRaises(ValidationError):
            m.save()
        with self.assertRaises(ValidationError):
            m.delete()
        with self.assertRaises(ValidationError), transaction.atomic():
            StockMovement.objects.all().delete()
        self.assertEqual(StockMovement.objects.count(), 2)

    def test_item_with_history_cannot_be_deleted(self):
        from django.db.models import ProtectedError

        with self.assertRaises(ProtectedError), transaction.atomic():
            self.raw.delete()


class ConcurrencySafetyTests(InventoryTestCase):
    """Stale objects (as two simultaneous requests would hold) must not corrupt stock."""

    def test_stale_copies_cannot_oversell(self):
        tab_a = InventoryItem.objects.get(pk=self.packets.pk)
        tab_b = InventoryItem.objects.get(pk=self.packets.pk)  # both believe stock is 35
        record_movement(tab_a, T.DECREASE, "30", self.owner, reason="A")
        with self.assertRaises(ValidationError):
            record_movement(tab_b, T.DECREASE, "30", self.owner, reason="B")  # only 5 left
        self.packets.refresh_from_db()
        self.assertEqual(self.packets.quantity, D(5))

    def test_increments_from_stale_copies_all_count(self):
        copies = [InventoryItem.objects.get(pk=self.packets.pk) for _ in range(3)]
        for c in copies:
            record_movement(c, T.INCREASE, "1", self.owner, reason="+1")
        self.packets.refresh_from_db()
        self.assertEqual(self.packets.quantity, D(38))
        afters = list(self.packets.movements.order_by("pk").values_list("quantity_after", flat=True))
        self.assertEqual(afters, [D(35), D(36), D(37), D(38)])

    def test_correction_uses_current_stock_not_a_stale_copy(self):
        stale = InventoryItem.objects.get(pk=self.packets.pk)
        record_movement(self.packets, T.DECREASE, "5", self.owner, reason="sold")
        # The stale copy still says 35; the service re-reads under lock, so the correction is computed from 30.
        m = record_movement(stale, T.CORRECTION, "28", self.owner, reason="count")
        self.assertEqual((m.quantity_before, m.quantity_after), (D(30), D(28)))

    def test_saving_settings_never_overwrites_stock(self):
        settings_form_copy = InventoryItem.objects.get(pk=self.packets.pk)  # loaded when the page opened: 35
        record_movement(self.packets, T.INCREASE, "10", self.owner, reason="delivery")  # now 45
        settings_form_copy.reorder_level = D(12)
        settings_form_copy.save()
        self.packets.refresh_from_db()
        self.assertEqual(self.packets.quantity, D(45))
        self.assertEqual(self.packets.reorder_level, D(12))


class LowStockTests(InventoryTestCase):
    def test_states(self):
        item = InventoryItem.objects.get(pk=self.packets.pk)  # 35, reorder 10
        self.assertEqual(item.state, "OK")
        record_movement(item, T.DECREASE, "25", self.owner, reason="x")  # 10 -> at reorder level
        item.refresh_from_db()
        self.assertEqual(item.state, "LOW")
        item.minimum_level = D(5)
        item.save()
        record_movement(item, T.DECREASE, "6", self.owner, reason="x")  # 4 < minimum
        item.refresh_from_db()
        self.assertEqual(item.state, "BELOW_MIN")
        record_movement(item, T.DECREASE, "4", self.owner, reason="x")
        item.refresh_from_db()
        self.assertEqual(item.state, "OUT")
        annotated = InventoryItem.objects.with_stock_status().get(pk=item.pk)
        self.assertEqual(annotated.stock_state, "OUT")
        self.assertIn(item, InventoryItem.objects.needs_attention())
        self.assertNotIn(self.raw, InventoryItem.objects.needs_attention())

    def test_level_validation(self):
        item = InventoryItem(kind=InventoryItem.Kind.FINISHED_GOOD, variation=self.v400,
                             reorder_level=D(5), minimum_level=D(8), maximum_level=D(3))
        with self.assertRaises(ValidationError) as ctx:
            item.full_clean()
        self.assertIn("minimum_level", ctx.exception.message_dict)
        self.assertIn("maximum_level", ctx.exception.message_dict)
        item = InventoryItem(kind=InventoryItem.Kind.FINISHED_GOOD, variation=self.v400, reorder_level=D("2.5"))
        with self.assertRaises(ValidationError):
            item.full_clean()  # whole packets only

    def test_one_inventory_item_per_variation(self):
        with self.assertRaises(ValidationError):
            InventoryItem(kind=InventoryItem.Kind.FINISHED_GOOD, variation=self.v200).full_clean()

    def test_raw_names_unique(self):
        with self.assertRaises(ValidationError):
            InventoryItem(kind=InventoryItem.Kind.RAW_MATERIAL, name="unpacked black tea", stock_unit=self.kg).full_clean()
