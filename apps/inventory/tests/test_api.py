from django.urls import reverse
from rest_framework.test import APIClient

from apps.inventory.models import Purchase, StockMovement

from .helpers import D, InventoryTestCase, draft_purchase


class InventoryApiTests(InventoryTestCase):
    def setUp(self):
        super().setUp()
        self.api = APIClient()

    def test_access_by_role(self):
        purchase = draft_purchase(self.supplier, self.owner, [(self.packets, "1", None, "1")])
        urls = [reverse("api:inventory-item-list"), reverse("api:inventory-movement-list"),
                reverse("api:inventory-supplier-list"), reverse("api:inventory-purchase-list"),
                reverse("api:inventory-supplier-detail", args=[self.supplier.pk]),
                reverse("api:inventory-purchase-detail", args=[purchase.pk])]
        for user, expected in ((self.owner, 200), (self.manager, 200), (self.it_admin, 403), (self.cashier, 403),
                               (self.customer, 403), (None, 403)):
            self.api.force_authenticate(user)
            for url in urls:
                with self.subTest(user=getattr(user, "role", "anon"), url=url):
                    self.assertEqual(self.api.get(url).status_code, expected)

    def test_customer_cannot_adjust_or_receive(self):
        purchase = draft_purchase(self.supplier, self.owner, [(self.packets, "10", None, "1")])
        self.api.force_authenticate(self.customer)
        r = self.api.post(reverse("api:inventory-item-adjust", args=[self.packets.pk]),
                          {"movement_type": "INCREASE", "quantity": "100", "reason": "x"}, format="json")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.api.post(reverse("api:inventory-purchase-receive", args=[purchase.pk])).status_code, 403)
        self.packets.refresh_from_db()
        self.assertEqual(self.packets.quantity, D(35))

    def test_quantity_is_read_only_and_adjust_uses_ledger(self):
        self.api.force_authenticate(self.manager)
        url = reverse("api:inventory-item-detail", args=[self.packets.pk])
        r = self.api.patch(url, {"quantity": "9999", "reorder_level": "12"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.packets.refresh_from_db()
        self.assertEqual((self.packets.quantity, self.packets.reorder_level), (D(35), D(12)))
        r = self.api.post(reverse("api:inventory-item-adjust", args=[self.packets.pk]),
                          {"movement_type": "DAMAGE", "quantity": "2", "reason": "Crushed"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["quantity_after"], "33.000")
        r = self.api.post(reverse("api:inventory-item-adjust", args=[self.packets.pk]),
                          {"movement_type": "DECREASE", "quantity": "500", "reason": "x"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_manager_cannot_enable_negative_stock(self):
        self.api.force_authenticate(self.manager)
        r = self.api.patch(reverse("api:inventory-item-detail", args=[self.packets.pk]), {"allow_negative": True}, format="json")
        self.assertEqual(r.status_code, 400)
        self.api.force_authenticate(self.owner)
        r = self.api.patch(reverse("api:inventory-item-detail", args=[self.packets.pk]), {"allow_negative": True}, format="json")
        self.assertEqual(r.status_code, 200)

    def test_movements_are_read_only(self):
        self.api.force_authenticate(self.owner)
        m = StockMovement.objects.first()
        url = reverse("api:inventory-movement-detail", args=[m.pk])
        self.assertEqual(self.api.delete(url).status_code, 405)
        self.assertEqual(self.api.patch(url, {"reason": "edited"}, format="json").status_code, 405)
        self.assertEqual(self.api.post(reverse("api:inventory-movement-list"), {}, format="json").status_code, 405)

    def test_purchase_create_receive_twice_cancel(self):
        self.api.force_authenticate(self.manager)
        r = self.api.post(reverse("api:inventory-purchase-list"), {
            "supplier": self.supplier.pk, "purchase_date": "2026-10-30",
            "lines": [{"item": self.raw.pk, "quantity": "500", "unit": self.g.pk, "unit_cost": "1.10"},
                      {"item": self.packets.pk, "quantity": "6", "unit": None, "unit_cost": "300"}]}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        pid = r.json()["id"]
        self.assertEqual((r.json()["status"], r.json()["total"]), ("DRAFT", "2350.00"))
        self.assertEqual(self.api.post(reverse("api:inventory-purchase-receive", args=[pid])).status_code, 200)
        self.assertEqual(self.api.post(reverse("api:inventory-purchase-receive", args=[pid])).status_code, 400)
        self.raw.refresh_from_db()
        self.packets.refresh_from_db()
        self.assertEqual((self.raw.quantity, self.packets.quantity), (D("20.5"), D(41)))
        self.assertEqual(self.api.patch(reverse("api:inventory-purchase-detail", args=[pid]), {"notes": "x"}, format="json").status_code, 400)
        self.assertEqual(self.api.post(reverse("api:inventory-purchase-cancel", args=[pid]), {"reason": "x"}).status_code, 400)
        self.assertEqual(self.api.delete(reverse("api:inventory-purchase-detail", args=[pid])).status_code, 405)

    def test_purchase_validation(self):
        self.api.force_authenticate(self.owner)
        url = reverse("api:inventory-purchase-list")
        base = {"supplier": self.supplier.pk, "purchase_date": "2026-10-30"}
        self.assertEqual(self.api.post(url, {**base, "lines": []}, format="json").status_code, 400)
        bad_unit = [{"item": self.raw.pk, "quantity": "5", "unit": self.bags.pk, "unit_cost": "1"}]
        self.assertEqual(self.api.post(url, {**base, "lines": bad_unit}, format="json").status_code, 400)
        half_packet = [{"item": self.packets.pk, "quantity": "1.5", "unit": None, "unit_cost": "1"}]
        self.assertEqual(self.api.post(url, {**base, "lines": half_packet}, format="json").status_code, 400)
        self.assertFalse(Purchase.objects.exists())

    def test_supplier_api_has_no_delete(self):
        self.api.force_authenticate(self.owner)
        self.assertEqual(self.api.delete(reverse("api:inventory-supplier-detail", args=[self.supplier.pk])).status_code, 405)
        r = self.api.post(reverse("api:inventory-supplier-list"), {"name": "HILL COUNTRY estates"}, format="json")
        self.assertEqual(r.status_code, 400)  # duplicate name
