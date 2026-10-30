import json
import uuid

from django.test import Client
from django.urls import reverse

from apps.accounts.tests.helpers import PASSWORD
from apps.orders.models import Order
from apps.payments.models import Payment
from apps.pos import services
from apps.pos.models import CashierShift, CashMovement, PosSettings, ReceiptPrint

from .helpers import BANK, D, PosTestCase


class PosViewTestCase(PosTestCase):
    def login(self, user):
        self.client.login(username=user.username, password=PASSWORD)

    def checkout(self, **overrides):
        payload = {"token": str(uuid.uuid4()), "lines": [{"id": self.b200.pk, "qty": 2}, {"id": self.k10.pk, "qty": 1}],
                   "payment_method": "CASH", "cash_tendered": "2000", "expected_total": "1300.00"}
        payload.update(overrides)
        return self.client.post(reverse("pos:checkout"), json.dumps(payload), content_type="application/json")


class AccessTests(PosViewTestCase):
    def test_role_matrix(self):
        sale = (self.open(), self.sell())[1]
        shift = sale.shift
        urls = {
            "terminal": reverse("pos:terminal"), "sales": reverse("pos:sales"),
            "sale": reverse("pos:sale_detail", args=[sale.number]), "receipt": reverse("pos:receipt", args=[sale.number]),
            "shifts": reverse("pos:shifts"), "shift": reverse("pos:shift_detail", args=[shift.pk]),
            "settings": reverse("pos:settings"),
        }
        expected = {
            self.owner: {"terminal": 200, "sales": 200, "sale": 200, "receipt": 200, "shifts": 200, "shift": 200, "settings": 200},
            self.manager: {"terminal": 403, "sales": 200, "sale": 200, "receipt": 200, "shifts": 200, "shift": 200, "settings": 403},
            self.cashier: {"terminal": 200, "sales": 200, "sale": 200, "receipt": 200, "shifts": 200, "shift": 200, "settings": 403},
            self.cashier2: {"terminal": 200, "sales": 200, "sale": 404, "receipt": 404, "shifts": 200, "shift": 404, "settings": 403},
            self.it_admin: {k: 403 for k in urls},
            self.customer: {k: 403 for k in urls},
        }
        for user, codes in expected.items():
            self.login(user)
            for name, url in urls.items():
                self.assertEqual(self.client.get(url).status_code, codes[name], f"{user.username} {name}")
        self.client.logout()
        response = self.client.get(urls["terminal"])
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:staff_login"), response["Location"])

    def test_post_actions_need_permission(self):
        self.open()
        sale = self.sell()
        self.login(self.cashier2)
        self.assertEqual(self.client.post(reverse("pos:refund", args=[sale.number]), {"reason": "x"}).status_code, 403)
        self.assertEqual(self.client.post(reverse("pos:reprint", args=[sale.number])).status_code, 404)
        self.assertEqual(self.client.post(reverse("pos:cash_movement", args=[sale.shift.pk]),
                                          {"kind": "CASH_OUT", "amount": "10", "reason": "x"}).status_code, 404)
        self.login(self.manager)
        self.assertEqual(self.checkout().status_code, 403)
        self.login(self.customer)
        self.assertEqual(self.checkout().status_code, 403)
        self.assertFalse(CashMovement.objects.exists())
        sale.refresh_from_db()
        self.assertEqual(sale.status, Order.Status.COMPLETED)


class TerminalTests(PosViewTestCase):
    def test_open_shift_first(self):
        self.login(self.cashier)
        response = self.client.get(reverse("pos:terminal"))
        self.assertTemplateUsed(response, "pos/open_shift.html")
        response = self.client.post(reverse("pos:shift_open"), {"opening_cash": "2500"})
        self.assertRedirects(response, reverse("pos:terminal"))
        self.assertEqual(CashierShift.objects.get(cashier=self.cashier).opening_cash, D("2500"))
        self.client.post(reverse("pos:shift_open"), {"opening_cash": "10"})  # duplicate refused
        self.assertEqual(CashierShift.objects.filter(cashier=self.cashier).count(), 1)

    def test_till_lists_only_sellable_products(self):
        self.open()
        self.login(self.cashier)
        response = self.client.get(reverse("pos:terminal"))
        self.assertTemplateUsed(response, "pos/terminal.html")
        ids = {p["id"] for p in response.context["pos_data"]["products"]}
        self.assertEqual(ids, {self.b200.pk, self.g25.pk, self.k10.pk})
        product = next(p for p in response.context["pos_data"]["products"] if p["id"] == self.g25.pk)
        self.assertEqual((product["price"], product["stock"], product["sku"]), ("450.00", 3, self.g25.sku))
        self.assertNotContains(response, "399")  # no wholesale prices
        self.assertEqual(response.context["pos_data"]["discountLimit"], "5.00")


class CheckoutEndpointTests(PosViewTestCase):
    def setUp(self):
        super().setUp()
        self.shift = self.open()
        self.login(self.cashier)

    def test_successful_sale(self):
        response = self.checkout()
        self.assertEqual(response.status_code, 200)
        data = response.json()
        order = Order.objects.get(number=data["number"])
        self.assertEqual(data["receipt_url"], reverse("pos:receipt", args=[order.number]) + "?new=1")
        self.assertEqual((order.total, order.cashier, order.shift), (D("1300"), self.cashier, self.shift))
        self.assertEqual(order.payments.get().change_given, D("700"))

    def test_double_submit_records_one_sale(self):
        token = str(uuid.uuid4())
        first = self.checkout(token=token).json()
        second = self.checkout(token=token).json()
        self.assertEqual(first["number"], second["number"])
        self.assertEqual(Order.objects.filter(channel=Order.Channel.POS).count(), 1)
        self.assertEqual(self.stock(self.b200), D("8"))

    def test_browser_prices_are_ignored(self):
        response = self.checkout(lines=[{"id": self.b200.pk, "qty": 1, "price": "1"}], total="1", expected_total="500.00",
                                 cash_tendered="500")
        self.assertEqual(Order.objects.get(number=response.json()["number"]).total, D("500"))

    def test_errors_are_reported(self):
        cases = [{"cash_tendered": "100"}, {"lines": []}, {"lines": [{"id": self.g25.pk, "qty": 50}]},
                 {"payment_method": "BANK_TRANSFER", "bank_reference": ""}, {"expected_total": "1.00"}]
        for overrides in cases:
            response = self.checkout(**overrides)
            self.assertEqual(response.status_code, 400, overrides)
            self.assertFalse(response.json()["ok"])
            self.assertTrue(response.json()["error"])
        self.assertEqual(self.client.post(reverse("pos:checkout"), "not json", content_type="application/json").status_code, 400)
        self.assertEqual(self.checkout(token="nope").status_code, 400)
        self.assertFalse(Order.objects.filter(channel=Order.Channel.POS).exists())

    def test_discount_approval_with_manager_sign_in(self):
        discount = {"discount_type": "PERCENT", "discount_value": "10", "discount_reason": "Bulk", "expected_total": "1170.00"}
        response = self.checkout(**discount)
        self.assertEqual(response.json()["code"], "needs_approval")
        response = self.checkout(**discount, approver_username="manager", approver_password="wrong")
        self.assertEqual(response.status_code, 400)
        response = self.checkout(**discount, approver_username="manager", approver_password=PASSWORD)
        order = Order.objects.get(number=response.json()["number"])
        self.assertEqual((order.discount_amount, order.discount_approved_by, order.discount_applied_by),
                         (D("130.00"), self.manager, self.cashier))

    def test_approval_attempts_are_throttled(self):
        discount = {"discount_type": "PERCENT", "discount_value": "10", "discount_reason": "Bulk", "expected_total": "1170.00",
                    "approver_username": "manager"}
        for _ in range(5):
            self.checkout(**discount, approver_password="wrong")
        response = self.checkout(**discount, approver_password=PASSWORD)
        self.assertEqual(response.status_code, 429)
        self.assertFalse(Order.objects.filter(channel=Order.Channel.POS).exists())

    def test_csrf_required(self):
        client = Client(enforce_csrf_checks=True)
        client.login(username="cashier", password=PASSWORD)
        response = client.post(reverse("pos:checkout"), json.dumps({"token": str(uuid.uuid4())}), content_type="application/json")
        self.assertEqual(response.status_code, 403)


class ReceiptTests(PosViewTestCase):
    def setUp(self):
        super().setUp()
        self.open()
        self.sale = self.sell(tendered="2000", discount_type="FIXED", discount_value="50", discount_reason="Promo")

    def test_receipt_contents(self):
        config = PosSettings.load()
        config.business_address, config.business_phone = "No. 12, Peradeniya Road, Kandy", "081 222 3333"
        config.save()
        self.login(self.cashier)
        response = self.client.get(reverse("pos:receipt", args=[self.sale.number]) + "?new=1")
        for text in (self.sale.number, "LEO PRODUCTS", "images/leo-logo.png", "Peradeniya Road", "081 222 3333",
                     "Black Tea", "1,250.00", "Discount", "2,000.00", "750.00", "Cash", "Cashier"):
            self.assertContains(response, text)
        self.assertNotContains(response, "COPY")
        self.assertContains(response, "receipt-page--thermal")
        self.assertContains(self.client.get(reverse("pos:receipt", args=[self.sale.number]) + "?size=a4"), "receipt-page--a4")

    def test_reprints_are_logged_and_marked(self):
        self.login(self.cashier)
        response = self.client.post(reverse("pos:reprint", args=[self.sale.number]), {"size": "a4"})
        self.assertRedirects(response, reverse("pos:receipt", args=[self.sale.number]) + "?size=a4")
        self.assertEqual(ReceiptPrint.objects.get(order=self.sale).printed_by, self.cashier)
        page = self.client.get(response["Location"])
        self.assertContains(page, "COPY")
        self.assertContains(page, "reprint 1")
        self.login(self.manager)
        self.assertContains(self.client.get(reverse("pos:receipt", args=[self.sale.number]) + "?new=1"), "COPY")

    def test_bank_sale_receipt_says_unconfirmed(self):
        sale = self.sell(method=BANK)
        self.login(self.cashier)
        self.assertContains(self.client.get(reverse("pos:receipt", args=[sale.number])), "not yet confirmed")

    def test_voided_receipt_marked(self):
        services.refund_sale(self.sale, self.manager, "Wrong item", drawer_shift=self.sale.shift)
        self.login(self.manager)
        self.assertContains(self.client.get(reverse("pos:receipt", args=[self.sale.number])), "VOIDED")


class SalesHistoryTests(PosViewTestCase):
    def setUp(self):
        super().setUp()
        self.open()
        self.cash_sale = self.sell()
        self.bank_sale = self.sell(method=BANK)
        self.open(self.cashier2)
        self.other_sale = self.sell(user=self.cashier2, lines=[(self.k10.pk, 1)])
        self.online = self.place()

    def test_cashier_sees_own_sales_only(self):
        self.login(self.cashier)
        response = self.client.get(reverse("pos:sales"))
        self.assertContains(response, self.cash_sale.number)
        self.assertNotContains(response, self.other_sale.number)
        self.assertNotContains(response, self.online.number)
        self.assertNotIn("cashier", response.context["filter_form"].fields)

    def test_manager_search_and_filters(self):
        self.login(self.manager)
        url = reverse("pos:sales")
        response = self.client.get(url)
        for order in (self.cash_sale, self.bank_sale, self.other_sale):
            self.assertContains(response, order.number)
        response = self.client.get(url, {"payment_method": "BANK_TRANSFER"})
        self.assertContains(response, self.bank_sale.number)
        self.assertNotContains(response, self.cash_sale.number)
        response = self.client.get(url, {"cashier": self.cashier2.pk})
        self.assertContains(response, self.other_sale.number)
        self.assertNotContains(response, self.bank_sale.number)
        response = self.client.get(url, {"q": self.cash_sale.number})
        self.assertEqual(list(response.context["page_obj"]), [self.cash_sale])
        response = self.client.get(url, {"date_from": "2000-01-01", "date_to": "2000-01-02"})
        self.assertContains(response, "No sales found")
        self.assertEqual(response.context["today"]["sales_count"], 3)

    def test_online_order_pages_stay_separate(self):
        self.login(self.manager)
        response = self.client.get(reverse("orders:staff_list"))
        self.assertContains(response, self.online.number)
        self.assertNotContains(response, self.cash_sale.number)
        self.assertRedirects(self.client.get(reverse("orders:staff_detail", args=[self.cash_sale.number])),
                             reverse("pos:sale_detail", args=[self.cash_sale.number]))
        self.assertEqual(self.client.get(reverse("pos:sale_detail", args=[self.online.number])).status_code, 404)

    def test_manager_verifies_till_transfer_from_sale_page(self):
        self.login(self.manager)
        page = self.client.get(reverse("pos:sale_detail", args=[self.bank_sale.number]))
        payment = self.bank_sale.payments.get()
        self.assertContains(page, reverse("payments:review", args=[payment.reference]))
        response = self.client.post(reverse("payments:review", args=[payment.reference]), {"decision": "approve"})
        self.assertRedirects(response, reverse("pos:sale_detail", args=[self.bank_sale.number]))
        self.bank_sale.refresh_from_db()
        self.assertEqual(self.bank_sale.status, Order.Status.COMPLETED)

    def test_cashier_cannot_verify(self):
        self.login(self.cashier)
        payment = self.bank_sale.payments.get()
        self.assertNotContains(self.client.get(reverse("pos:sale_detail", args=[self.bank_sale.number])),
                               reverse("payments:review", args=[payment.reference]))
        self.assertEqual(self.client.post(reverse("payments:review", args=[payment.reference]),
                                          {"decision": "approve"}).status_code, 403)
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.PENDING_VERIFICATION)

    def test_refund_through_page(self):
        self.login(self.manager)
        url = reverse("pos:refund", args=[self.cash_sale.number])
        self.client.post(url, {"reason": "Faulty"})  # cash refund without a drawer: refused
        self.cash_sale.refresh_from_db()
        self.assertEqual(self.cash_sale.status, Order.Status.COMPLETED)
        self.client.post(url, {"reason": "Faulty", "drawer": self.cash_sale.shift.pk})
        self.cash_sale.refresh_from_db()
        self.assertEqual(self.cash_sale.status, Order.Status.CANCELLED)
        self.assertEqual(self.stock(self.b200), D("6"))  # 2 restored, bank sale's 2 still sold


class ShiftPageTests(PosViewTestCase):
    def setUp(self):
        super().setUp()
        self.shift = self.open()
        self.sell()

    def test_cashier_cash_movement_and_close(self):
        self.login(self.cashier)
        self.client.post(reverse("pos:cash_movement", args=[self.shift.pk]), {"kind": "CASH_OUT", "amount": "300", "reason": "Bank deposit"})
        self.assertEqual(services.shift_summary(self.shift).expected_cash, D("2000"))
        page = self.client.get(reverse("pos:shift_close", args=[self.shift.pk]))
        self.assertContains(page, "2,000.00")
        response = self.client.post(reverse("pos:shift_close", args=[self.shift.pk]), {"counted_cash": "1990"})
        self.assertEqual(response.status_code, 200)  # difference needs a note
        response = self.client.post(reverse("pos:shift_close", args=[self.shift.pk]), {"counted_cash": "1990", "closing_note": "Coins short"})
        self.assertRedirects(response, reverse("pos:shift_detail", args=[self.shift.pk]))
        self.shift.refresh_from_db()
        self.assertEqual((self.shift.status, self.shift.difference), (CashierShift.Status.CLOSED, D("-10")))
        # Closed: no more changes, even through the pages
        self.client.post(reverse("pos:cash_movement", args=[self.shift.pk]), {"kind": "CASH_IN", "amount": "5", "reason": "x"})
        self.assertEqual(self.shift.cash_movements.count(), 1)
        self.assertRedirects(self.client.get(reverse("pos:shift_close", args=[self.shift.pk])),
                             reverse("pos:shift_detail", args=[self.shift.pk]))

    def test_shift_lists_by_role(self):
        other = self.open(self.cashier2)
        self.login(self.cashier)
        response = self.client.get(reverse("pos:shifts"))
        self.assertContains(response, self.shift.code)
        self.assertNotContains(response, other.code)
        self.login(self.manager)
        response = self.client.get(reverse("pos:shifts"))
        self.assertContains(response, self.shift.code)
        self.assertContains(response, other.code)
        self.assertEqual(self.client.get(reverse("pos:shift_close", args=[other.pk])).status_code, 200)

    def test_dashboards_show_real_pos_figures(self):
        for user, title in ((self.cashier, "My sales today"), (self.owner, "Today's POS sales"), (self.manager, "Today's POS sales")):
            self.login(user)
            response = self.client.get(reverse("dashboard:home"), follow=True)
            self.assertContains(response, title)
            self.assertContains(response, "1,300.00")
        self.login(self.it_admin)
        response = self.client.get(reverse("dashboard:home"), follow=True)
        self.assertNotContains(response, "Point of sale today")


class SettingsTests(PosViewTestCase):
    def test_owner_updates_settings_with_validation(self):
        self.login(self.owner)
        url = reverse("pos:settings")
        response = self.client.post(url, {"cashier_discount_limit": "30", "manager_discount_limit": "20", "receipt_footer": "Thanks"})
        self.assertIn("cashier_discount_limit", response.context["form"].errors)
        response = self.client.post(url, {"cashier_discount_limit": "101", "manager_discount_limit": "20"})
        self.assertEqual(response.status_code, 200)
        response = self.client.post(url, {"cashier_discount_limit": "2", "manager_discount_limit": "15",
                                          "business_phone": "081 222 3333", "receipt_footer": "Thanks"})
        self.assertRedirects(response, url)
        config = PosSettings.load()
        self.assertEqual((config.cashier_discount_limit, config.business_phone), (D("2"), "081 222 3333"))
