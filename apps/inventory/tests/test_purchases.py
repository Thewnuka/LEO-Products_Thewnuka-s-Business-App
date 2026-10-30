from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.inventory.models import Purchase, PurchaseLine, StockMovement, Supplier
from apps.inventory.services import cancel_purchase, next_purchase_reference, receive_purchase

from .helpers import D, InventoryTestCase, draft_purchase


class PurchaseWorkflowTests(InventoryTestCase):
    def setUp(self):
        super().setUp()
        # 5 kg loose tea bought as 5000 g, plus 24 packets of 200g tea
        self.purchase = draft_purchase(self.supplier, self.manager, [
            (self.raw, "5000", self.g, "1.25"),        # LKR 1.25 per gram
            (self.packets, "24", None, "310.00"),
        ])

    def test_reference_and_totals(self):
        self.assertRegex(self.purchase.reference, r"^PO-2026-\d{4}$")
        self.assertEqual(self.purchase.total, D("13690.00"))  # 6250 + 7440
        self.assertEqual(self.purchase.subtotal, self.purchase.total)
        self.assertEqual(next_purchase_reference(self.purchase.purchase_date), "PO-2026-0002")

    def test_draft_does_not_change_stock(self):
        self.raw.refresh_from_db()
        self.packets.refresh_from_db()
        self.assertEqual((self.raw.quantity, self.packets.quantity), (D(20), D(35)))
        self.assertFalse(StockMovement.objects.filter(movement_type="PURCHASE").exists())

    def test_receiving_adds_stock_once_with_movements(self):
        receive_purchase(self.purchase, self.owner)
        self.raw.refresh_from_db()
        self.packets.refresh_from_db()
        self.assertEqual((self.raw.quantity, self.packets.quantity), (D(25), D(59)))  # 5000 g = 5 kg
        moves = StockMovement.objects.filter(purchase=self.purchase).order_by("pk")
        self.assertEqual([(m.item_id, m.quantity_change) for m in moves], [(self.raw.pk, D(5)), (self.packets.pk, D(24))])
        self.assertTrue(all(m.created_by == self.owner and m.purchase_line_id for m in moves))
        self.purchase.refresh_from_db()
        self.assertEqual(self.purchase.status, Purchase.Status.RECEIVED)
        self.assertEqual(self.purchase.received_by, self.owner)

    def test_receiving_twice_does_not_add_twice(self):
        stale_copy = Purchase.objects.get(pk=self.purchase.pk)  # e.g. a second browser tab
        receive_purchase(self.purchase, self.owner)
        with self.assertRaises(ValidationError) as ctx:
            receive_purchase(stale_copy, self.manager)
        self.assertIn("already received", str(ctx.exception))
        self.packets.refresh_from_db()
        self.assertEqual(self.packets.quantity, D(59))
        self.assertEqual(StockMovement.objects.filter(purchase=self.purchase).count(), 2)

    def test_database_blocks_second_movement_for_same_line(self):
        receive_purchase(self.purchase, self.owner)
        line = self.purchase.lines.first()
        with self.assertRaises(IntegrityError), transaction.atomic():
            StockMovement.objects.create(item=line.item, movement_type="PURCHASE", quantity_change=D(1),
                                         quantity_before=D(0), quantity_after=D(1), purchase_line=line)

    def test_cancelled_purchase_never_adds_stock(self):
        cancel_purchase(self.purchase, self.owner, "Supplier could not deliver")
        with self.assertRaises(ValidationError):
            receive_purchase(self.purchase, self.owner)
        self.packets.refresh_from_db()
        self.assertEqual(self.packets.quantity, D(35))
        self.purchase.refresh_from_db()
        self.assertEqual((self.purchase.status, self.purchase.cancel_reason), (Purchase.Status.CANCELLED, "Supplier could not deliver"))

    def test_received_purchase_cannot_be_cancelled(self):
        receive_purchase(self.purchase, self.owner)
        with self.assertRaises(ValidationError):
            cancel_purchase(self.purchase, self.owner, "oops")

    def test_cancel_needs_reason(self):
        with self.assertRaises(ValidationError):
            cancel_purchase(self.purchase, self.owner, " ")

    def test_failed_line_rolls_back_whole_receive(self):
        bad = draft_purchase(self.supplier, self.owner, [(self.packets, "1", None, "10")])
        PurchaseLine.objects.filter(purchase=bad).update(quantity=D("1.5"))  # half a packet: invalid
        with self.assertRaises(ValidationError):
            receive_purchase(bad, self.owner)
        bad.refresh_from_db()
        self.assertEqual(bad.status, Purchase.Status.DRAFT)
        self.assertFalse(StockMovement.objects.filter(purchase=bad).exists())

    def test_empty_purchase_cannot_be_received(self):
        empty = draft_purchase(self.supplier, self.owner, [])
        with self.assertRaises(ValidationError):
            receive_purchase(empty, self.owner)

    def test_line_unit_validation(self):
        line = PurchaseLine(purchase=self.purchase, item=self.raw, quantity=D(5), unit=self.bags, unit_cost=D(1))
        with self.assertRaises(ValidationError):
            line.full_clean()

    def test_supplier_with_purchases_cannot_be_deleted(self):
        from django.db.models import ProtectedError

        with self.assertRaises(ProtectedError), transaction.atomic():
            Supplier.objects.get(pk=self.supplier.pk).delete()
