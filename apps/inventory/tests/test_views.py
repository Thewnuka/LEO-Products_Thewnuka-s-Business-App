from decimal import Decimal

from django.urls import reverse

from apps.inventory.models import InventoryItem, Purchase, StockMovement, Supplier

from .helpers import D, InventoryTestCase, draft_purchase, raw_item


class PermissionTests(InventoryTestCase):
    def urls(self):
        purchase = draft_purchase(self.supplier, self.owner, [(self.packets, "1", None, "10")])
        return {
            "inventory": [("get", reverse("inventory:dashboard")), ("get", reverse("inventory:item_list")),
                          ("get", reverse("inventory:item_create")), ("get", reverse("inventory:item_detail", args=[self.packets.pk])),
                          ("get", reverse("inventory:item_update", args=[self.packets.pk])),
                          ("get", reverse("inventory:item_adjust", args=[self.packets.pk])),
                          ("post", reverse("inventory:item_adjust", args=[self.packets.pk])),
                          ("get", reverse("inventory:movement_list"))],
            "suppliers": [("get", reverse("inventory:supplier_list")), ("get", reverse("inventory:supplier_create")),
                          ("get", reverse("inventory:supplier_detail", args=[self.supplier.pk])),
                          ("get", reverse("inventory:supplier_update", args=[self.supplier.pk])),
                          ("post", reverse("inventory:supplier_toggle", args=[self.supplier.pk]))],
            "purchases": [("get", reverse("inventory:purchase_list")), ("get", reverse("inventory:purchase_create")),
                          ("get", reverse("inventory:purchase_detail", args=[purchase.pk])),
                          ("get", reverse("inventory:purchase_update", args=[purchase.pk])),
                          ("get", reverse("inventory:purchase_receive", args=[purchase.pk])),
                          ("post", reverse("inventory:purchase_receive", args=[purchase.pk])),
                          ("post", reverse("inventory:purchase_cancel", args=[purchase.pk]))],
        }

    def test_cashier_it_admin_customer_are_refused_and_nothing_changes(self):
        groups = self.urls()
        for user in (self.cashier, self.it_admin, self.customer):
            self.client.force_login(user)
            for urls in groups.values():
                for method, url in urls:
                    with self.subTest(role=user.role, url=url, method=method):
                        data = {"movement_type": "DECREASE", "quantity": "35", "reason": "x", "confirm": "1"} if method == "post" else None
                        self.assertEqual(getattr(self.client, method)(url, data).status_code, 403)
        self.packets.refresh_from_db()
        self.assertEqual(self.packets.quantity, D(35))
        self.assertTrue(Supplier.objects.get(pk=self.supplier.pk).is_active)
        self.assertEqual(Purchase.objects.get().status, Purchase.Status.DRAFT)

    def test_anonymous_redirected_to_staff_login(self):
        for urls in self.urls().values():
            for method, url in urls:
                with self.subTest(url=url):
                    r = getattr(self.client, method)(url)
                    self.assertEqual(r.status_code, 302)
                    self.assertTrue(r["Location"].startswith(reverse("accounts:staff_login")))

    def test_owner_and_manager_can_open_every_page(self):
        groups = self.urls()
        for user in (self.owner, self.manager):
            self.client.force_login(user)
            for urls in groups.values():
                for method, url in urls:
                    if method == "get":
                        with self.subTest(role=user.role, url=url):
                            self.assertEqual(self.client.get(url).status_code, 200)

    def test_only_owner_sees_negative_stock_setting(self):
        url = reverse("inventory:item_update", args=[self.packets.pk])
        self.client.force_login(self.owner)
        self.assertContains(self.client.get(url), 'name="allow_negative"')
        self.client.force_login(self.manager)
        self.assertNotContains(self.client.get(url), 'name="allow_negative"')
        self.client.post(url, {"reorder_level": "10", "minimum_level": "0", "count_label": "packets",
                               "is_active": "on", "allow_negative": "on"})
        self.packets.refresh_from_db()
        self.assertFalse(self.packets.allow_negative)  # manager cannot switch it on


class ItemPageTests(InventoryTestCase):
    def test_create_raw_material_with_opening_stock(self):
        self.client.force_login(self.manager)
        r = self.client.post(reverse("inventory:item_create"), {
            "kind": "RAW", "name": "Unpacked Ginger Tea", "stock_unit": self.kg.pk, "opening_quantity": "12.5",
            "reorder_level": "5", "minimum_level": "2", "count_label": "packets", "is_active": "on"})
        item = InventoryItem.objects.get(name="Unpacked Ginger Tea")
        self.assertRedirects(r, reverse("inventory:item_detail", args=[item.pk]))
        self.assertEqual(item.quantity, D("12.5"))
        self.assertEqual(item.movements.get().movement_type, "OPENING")

    def test_create_finished_item_for_variation(self):
        self.client.force_login(self.owner)
        self.client.post(reverse("inventory:item_create"), {
            "kind": "FINISHED", "variation": self.v400.pk, "opening_quantity": "18", "count_label": "packets",
            "reorder_level": "5", "minimum_level": "0", "is_active": "on"})
        item = InventoryItem.objects.get(variation=self.v400)
        self.assertEqual(item.quantity_display, "18 packets")
        r = self.client.post(reverse("inventory:item_create"), {
            "kind": "FINISHED", "variation": self.v200.pk, "opening_quantity": "1", "count_label": "packets",
            "reorder_level": "0", "minimum_level": "0"})
        self.assertIn("variation", r.context["form"].errors)  # already tracked

    def test_fractional_packets_rejected(self):
        self.client.force_login(self.owner)
        r = self.client.post(reverse("inventory:item_create"), {
            "kind": "FINISHED", "variation": self.v400.pk, "opening_quantity": "2.5", "count_label": "packets",
            "reorder_level": "0", "minimum_level": "0"})
        self.assertIn("opening_quantity", r.context["form"].errors)
        self.assertFalse(InventoryItem.objects.filter(variation=self.v400).exists())

    def test_adjust_requires_confirmation_step(self):
        self.client.force_login(self.manager)
        url = reverse("inventory:item_adjust", args=[self.packets.pk])
        data = {"movement_type": "DAMAGE", "quantity": "3", "reason": "Water damage"}
        r = self.client.post(url, data)
        self.assertContains(r, "Please confirm this stock change")
        self.assertContains(r, "32 packets")
        self.packets.refresh_from_db()
        self.assertEqual(self.packets.quantity, D(35))  # not saved yet
        r = self.client.post(url, {**data, "confirm": "1"})
        self.assertRedirects(r, reverse("inventory:item_detail", args=[self.packets.pk]))
        self.packets.refresh_from_db()
        self.assertEqual(self.packets.quantity, D(32))
        self.assertEqual(StockMovement.objects.filter(item=self.packets, movement_type="DAMAGE").get().created_by, self.manager)

    def test_adjust_without_reason_or_beyond_stock(self):
        self.client.force_login(self.manager)
        url = reverse("inventory:item_adjust", args=[self.packets.pk])
        r = self.client.post(url, {"movement_type": "DECREASE", "quantity": "3", "reason": ""})
        self.assertIn("reason", r.context["form"].errors)
        r = self.client.post(url, {"movement_type": "DECREASE", "quantity": "99", "reason": "x"})
        self.assertTrue(r.context["preview"].would_go_negative)
        self.assertNotContains(r, "Confirm and record")
        r = self.client.post(url, {"movement_type": "DECREASE", "quantity": "99", "reason": "x", "confirm": "1"})
        self.assertContains(r, "Not enough stock")
        self.packets.refresh_from_db()
        self.assertEqual(self.packets.quantity, D(35))

    def test_adjust_raw_in_grams(self):
        self.client.force_login(self.owner)
        url = reverse("inventory:item_adjust", args=[self.raw.pk])
        self.client.post(url, {"movement_type": "DECREASE", "quantity": "250", "unit": self.g.pk, "reason": "Tasting", "confirm": "1"})
        self.raw.refresh_from_db()
        self.assertEqual(self.raw.quantity, D("19.75"))

    def test_back_to_edit_keeps_values_and_saves_nothing(self):
        self.client.force_login(self.owner)
        url = reverse("inventory:item_adjust", args=[self.packets.pk])
        r = self.client.post(url, {"movement_type": "INCREASE", "quantity": "4", "reason": "Found", "edit": "1"})
        self.assertNotIn("preview", r.context)
        self.assertEqual(r.context["form"]["quantity"].value(), "4")
        self.packets.refresh_from_db()
        self.assertEqual(self.packets.quantity, D(35))


class SearchFilterTests(InventoryTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.owner)
        for i in range(25):
            raw_item(f"Raw Item {i:02d}", self.kg, self.owner, opening=str(i), reorder="5")

    def names(self, **params):
        return [i.display_name for i in self.client.get(reverse("inventory:item_list"), params).context["page_obj"]]

    def test_search_and_filters(self):
        self.assertEqual(self.names(q="unpacked"), ["Unpacked Black Tea"])  # raw material by name
        self.assertEqual(self.names(q=self.v200.sku), ["Black Tea – 200g"])
        self.assertEqual(self.names(kind="FINISHED"), ["Black Tea – 200g"])
        self.assertEqual(self.names(unit="packets"), ["Black Tea – 200g"])
        self.assertEqual(len(self.names(unit=self.kg.pk, sort="-qty")), 20)  # page 1 of 26 kg items
        self.assertEqual(self.names(state="OUT"), ["Raw Item 00"])
        low = self.names(state="LOW")
        self.assertEqual(set(low), {f"Raw Item {i:02d}" for i in range(1, 6)})
        self.assertEqual(self.names(category=self.leo_tea.pk), ["Black Tea – 200g"])
        self.assertEqual(self.names(state="ATTENTION", sort="qty")[0], "Raw Item 00")

    def test_sort_and_pagination_keep_filters(self):
        r = self.client.get(reverse("inventory:item_list"), {"unit": self.kg.pk, "sort": "-qty"})
        self.assertEqual(r.context["page_obj"][0].display_name, "Raw Item 24")
        self.assertEqual(r.context["page_obj"].paginator.num_pages, 2)
        self.assertContains(r, f"unit={self.kg.pk}&amp;sort=-qty&page=2")
        r2 = self.client.get(reverse("inventory:item_list"), {"unit": self.kg.pk, "sort": "-qty", "page": 2})
        self.assertEqual(len(r2.context["page_obj"]), 6)

    def test_invalid_filter_values_ignored(self):
        r = self.client.get(reverse("inventory:item_list"), {"category": "abc", "state": "BOGUS", "unit": "999999"})
        self.assertEqual(r.status_code, 200)


class SupplierPageTests(InventoryTestCase):
    def test_create_edit_search_and_toggle(self):
        self.client.force_login(self.manager)
        r = self.client.post(reverse("inventory:supplier_create"), {
            "name": "Kandy Packaging", "contact_person": "Sunil", "phone": "+94 81 222 3333",
            "email": "Orders@Kandy.Example", "is_active": "on"})
        s = Supplier.objects.get(name="Kandy Packaging")
        self.assertRedirects(r, reverse("inventory:supplier_detail", args=[s.pk]))
        self.assertEqual(s.email, "orders@kandy.example")
        self.client.post(reverse("inventory:supplier_update", args=[s.pk]), {"name": "Kandy Packaging Ltd", "phone": "0812223333", "is_active": "on"})
        s.refresh_from_db()
        self.assertEqual(s.name, "Kandy Packaging Ltd")
        names = [x.name for x in self.client.get(reverse("inventory:supplier_list"), {"q": "kandy"}).context["page_obj"]]
        self.assertEqual(names, ["Kandy Packaging Ltd"])
        self.client.post(reverse("inventory:supplier_toggle", args=[s.pk]))
        s.refresh_from_db()
        self.assertFalse(s.is_active)
        names = [x.name for x in self.client.get(reverse("inventory:supplier_list"), {"active": "no"}).context["page_obj"]]
        self.assertEqual(names, ["Kandy Packaging Ltd"])

    def test_validation(self):
        self.client.force_login(self.manager)
        r = self.client.post(reverse("inventory:supplier_create"), {"name": "hill country ESTATES", "phone": "call me", "email": "bad"})
        errors = r.context["form"].errors
        self.assertIn("name", errors)
        self.assertIn("phone", errors)
        self.assertIn("email", errors)


class PurchasePageTests(InventoryTestCase):
    def line_data(self, rows):
        data = {"lines-TOTAL_FORMS": str(len(rows)), "lines-INITIAL_FORMS": "0", "lines-MIN_NUM_FORMS": "0", "lines-MAX_NUM_FORMS": "1000"}
        for i, (item, qty, unit, cost) in enumerate(rows):
            data.update({f"lines-{i}-item": item.pk, f"lines-{i}-quantity": qty, f"lines-{i}-unit": unit.pk if unit else "",
                         f"lines-{i}-unit_cost": cost})
        return data

    def test_create_draft_then_receive_through_pages(self):
        self.client.force_login(self.manager)
        data = {"supplier": self.supplier.pk, "purchase_date": "2026-10-30", "invoice_number": "INV-77",
                **self.line_data([(self.raw, "2", self.kg, "1100"), (self.packets, "10", None, "300")])}
        r = self.client.post(reverse("inventory:purchase_create"), data)
        purchase = Purchase.objects.get()
        self.assertRedirects(r, reverse("inventory:purchase_detail", args=[purchase.pk]))
        self.assertEqual((purchase.status, purchase.total, purchase.created_by), ("DRAFT", D("5200.00"), self.manager))
        self.packets.refresh_from_db()
        self.assertEqual(self.packets.quantity, D(35))

        r = self.client.get(reverse("inventory:purchase_receive", args=[purchase.pk]))
        self.assertContains(r, "45 packets")  # preview of stock after
        self.client.post(reverse("inventory:purchase_receive", args=[purchase.pk]))
        self.client.post(reverse("inventory:purchase_receive", args=[purchase.pk]))  # double click
        self.packets.refresh_from_db()
        self.raw.refresh_from_db()
        self.assertEqual((self.packets.quantity, self.raw.quantity), (D(45), D(22)))
        r = self.client.get(reverse("inventory:purchase_update", args=[purchase.pk]))
        self.assertRedirects(r, reverse("inventory:purchase_detail", args=[purchase.pk]))  # no edits after receiving

    def test_purchase_needs_a_line_and_valid_units(self):
        self.client.force_login(self.owner)
        base = {"supplier": self.supplier.pk, "purchase_date": "2026-10-30"}
        r = self.client.post(reverse("inventory:purchase_create"), {**base, **self.line_data([])})
        self.assertTrue(r.context["formset"].non_form_errors())
        r = self.client.post(reverse("inventory:purchase_create"), {**base, **self.line_data([(self.raw, "2", self.bags, "10")])})
        self.assertTrue(r.context["formset"].errors[0])
        r = self.client.post(reverse("inventory:purchase_create"), {**base, **self.line_data([(self.packets, "-2", None, "10")])})
        self.assertIn("quantity", r.context["formset"].errors[0])
        self.assertFalse(Purchase.objects.exists())

    def test_edit_draft_and_cancel(self):
        self.client.force_login(self.owner)
        purchase = draft_purchase(self.supplier, self.owner, [(self.packets, "5", None, "100")])
        line = purchase.lines.get()
        data = {"supplier": self.supplier.pk, "purchase_date": "2026-10-29", "invoice_number": "X",
                "lines-TOTAL_FORMS": "1", "lines-INITIAL_FORMS": "1", "lines-MIN_NUM_FORMS": "0", "lines-MAX_NUM_FORMS": "1000",
                "lines-0-id": line.pk, "lines-0-purchase": purchase.pk, "lines-0-item": self.packets.pk,
                "lines-0-quantity": "8", "lines-0-unit": "", "lines-0-unit_cost": "100"}
        self.client.post(reverse("inventory:purchase_update", args=[purchase.pk]), data)
        purchase.refresh_from_db()
        self.assertEqual(purchase.total, D("800.00"))
        self.client.post(reverse("inventory:purchase_cancel", args=[purchase.pk]), {"reason": "Ordered by mistake"})
        purchase.refresh_from_db()
        self.assertEqual(purchase.status, "CANCELLED")
        self.client.post(reverse("inventory:purchase_receive", args=[purchase.pk]))
        self.packets.refresh_from_db()
        self.assertEqual(self.packets.quantity, D(35))

    def test_purchase_filters(self):
        self.client.force_login(self.owner)
        other = Supplier.objects.create(name="Other Supplier")
        p1 = draft_purchase(self.supplier, self.owner, [(self.packets, "1", None, "1")])
        p1.invoice_number = "INV-ABC"
        p1.save()
        p2 = draft_purchase(other, self.owner, [(self.packets, "1", None, "1")])
        Purchase.objects.filter(pk=p2.pk).update(purchase_date="2026-01-15")
        get = lambda **q: [p.reference for p in self.client.get(reverse("inventory:purchase_list"), q).context["page_obj"]]  # noqa: E731
        self.assertEqual(get(q="inv-abc"), [p1.reference])
        self.assertEqual(get(q=p2.reference), [p2.reference])
        self.assertEqual(get(supplier=other.pk), [p2.reference])
        self.assertEqual(get(date_from="2026-10-01"), [p1.reference])
        self.assertEqual(get(date_to="2026-02-01"), [p2.reference])
        self.assertEqual(get(status="RECEIVED"), [])

    def test_supplier_purchase_history(self):
        self.client.force_login(self.owner)
        p = draft_purchase(self.supplier, self.owner, [(self.packets, "2", None, "50")])
        from apps.inventory.services import receive_purchase

        receive_purchase(p, self.owner)
        r = self.client.get(reverse("inventory:supplier_detail", args=[self.supplier.pk]))
        self.assertContains(r, p.reference)
        self.assertContains(r, "LKR 100.00")


class DashboardTests(InventoryTestCase):
    def test_real_counts(self):
        self.client.force_login(self.owner)
        raw_item("Empty Item", self.kg, self.owner)  # 0 -> out of stock
        from apps.inventory.services import record_movement

        record_movement(self.packets, "DECREASE", "30", self.owner, reason="sold")  # 5 <= reorder 10 -> low
        stats = self.client.get(reverse("inventory:dashboard")).context["stats"]
        self.assertEqual((stats["total_items"], stats["low_stock"], stats["out_of_stock"], stats["active_suppliers"]), (3, 1, 1, 1))
        self.assertEqual(stats["untracked_variations"], 1)  # the 400g variation
        self.assertEqual(stats["adjustments_30d"], [{"type": "Stock decrease", "code": "DECREASE", "count": 1}])
