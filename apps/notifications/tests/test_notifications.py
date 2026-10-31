import uuid
from datetime import timedelta
from io import StringIO

from django.core import mail
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.helpers import PASSWORD, make_user
from apps.finance.tests.helpers import FinanceTestCase
from apps.inventory.models import InventoryItem
from apps.notifications import events, services
from apps.notifications.alerts import business_alerts
from apps.notifications.models import AlertSettings, Category, Notification
from apps.orders import services as orders
from apps.orders.models import Order
from apps.orders.tests.helpers import PM, slip
from apps.payments import services as payments
from apps.pos import services as pos

D = __import__("decimal").Decimal


class NotifyTestCase(FinanceTestCase):
    def run_commit(self, fn, *args, **kwargs):
        with self.captureOnCommitCallbacks(execute=True):
            return fn(*args, **kwargs)

    def notes(self, user, **filters):
        return Notification.objects.filter(recipient=user, **filters)

    def login(self, user):
        self.client.login(username=user.username, password=PASSWORD)


class OrderAndPaymentEventTests(NotifyTestCase):
    def test_new_order_reaches_order_staff_and_customer_only(self):
        order = self.run_commit(self.place)
        for user in (self.owner, self.manager):
            note = self.notes(user, category=Category.ORDERS).get()
            self.assertIn(order.number, note.title)
            self.assertEqual(note.url, reverse("orders:staff_detail", args=[order.number]))
        for user in (self.cashier, self.it_admin):
            self.assertFalse(self.notes(user).exists())
        customer_note = self.notes(self.customer).get()
        self.assertEqual((customer_note.title, customer_note.url),
                         (f"Order {order.number} placed", reverse("orders:detail", args=[order.number])))

    def test_events_are_never_duplicated(self):
        order = self.run_commit(self.place)
        self.run_commit(events.new_online_order, order)          # same event again
        self.run_commit(events.customer_order_event, order, "placed")
        self.assertEqual(self.notes(self.owner).count(), 1)
        self.assertEqual(self.notes(self.customer).count(), 1)

    def test_each_status_change_notifies_customer_once(self):
        order = self.run_commit(self.place)
        self.run_commit(orders.change_status, order, Order.Status.CONFIRMED, self.manager)
        self.run_commit(orders.change_status, order, Order.Status.PROCESSING, self.manager)
        titles = list(self.notes(self.customer).values_list("title", flat=True))
        self.assertIn(f"Order {order.number}: confirmed", titles)
        self.assertIn(f"Order {order.number}: processing", titles)
        self.assertEqual(len(titles), 3)

    def test_transfer_to_verify_and_result(self):
        order = self.run_commit(self.place, method=PM.BANK_TRANSFER)
        payment = self.run_commit(payments.submit_bank_transfer, order, self.customer, "REF", slip())
        for user in (self.owner, self.manager):
            self.assertTrue(self.notes(user, category=Category.PAYMENTS).exists())
        self.assertFalse(self.notes(self.cashier, category=Category.PAYMENTS).exists())
        self.run_commit(payments.review_bank_transfer, payment, self.manager, approve=True)
        self.assertTrue(self.notes(self.customer, category=Category.PAYMENTS, level="success").exists())

    def test_cash_received_notifies_customer(self):
        order = self.run_commit(self.place)
        self.run_commit(payments.record_cash_payment, order, self.cashier)
        self.assertTrue(self.notes(self.customer, title__startswith="Payment received").exists())

    def test_customer_cancellation_alerts_staff(self):
        order = self.run_commit(self.place)
        self.run_commit(orders.cancel_order, order, self.customer, "Changed my mind", by_customer=True)
        self.assertTrue(self.notes(self.manager, title__contains="cancelled by the customer").exists())
        self.assertTrue(self.notes(self.customer, title__contains="was cancelled").exists())

    def test_customer_email_preference(self):
        pref = services.preference_for(self.customer)
        pref.email_order_updates = False
        pref.save()
        mail.outbox.clear()
        self.run_commit(self.place)
        self.assertEqual(len(mail.outbox), 0)                       # no email
        self.assertTrue(self.notes(self.customer).exists())         # still in-app

    def test_muted_category_is_skipped(self):
        pref = services.preference_for(self.manager)
        pref.muted_categories = [Category.ORDERS]
        pref.save()
        self.run_commit(self.place)
        self.assertFalse(self.notes(self.manager).exists())
        self.assertTrue(self.notes(self.owner).exists())

    def test_unsafe_links_are_dropped(self):
        self.run_commit(services.notify, [self.owner], Category.ALERTS, "x", url="https://evil.example/")
        self.run_commit(services.notify, [self.owner], Category.ALERTS, "y", url="//evil.example/")
        self.assertEqual(set(self.notes(self.owner).values_list("url", flat=True)), {""})


class OperationsEventTests(NotifyTestCase):
    def test_low_then_out_of_stock_only_when_crossing(self):
        item = InventoryItem.objects.get(variation=self.k10)   # 20 in stock
        item.reorder_level = D("5")
        item.save()
        self.open()
        self.run_commit(self.sell, lines=[(self.k10.pk, 10)])          # 10 left: nothing
        self.assertFalse(self.notes(self.manager, category=Category.STOCK).exists())
        self.run_commit(self.sell, lines=[(self.k10.pk, 6)])           # 4 left: low
        self.run_commit(self.sell, lines=[(self.k10.pk, 1)])           # 3 left: still low, no new alert
        self.assertEqual(self.notes(self.manager, category=Category.STOCK).count(), 1)
        self.run_commit(self.sell, lines=[(self.k10.pk, 3)])           # 0: out of stock
        titles = list(self.notes(self.manager, category=Category.STOCK).values_list("title", flat=True))
        self.assertEqual(len(titles), 2)
        self.assertTrue(any(t.startswith("Out of stock") for t in titles))
        self.assertTrue(self.notes(self.owner, category=Category.STOCK).exists())
        self.assertFalse(self.notes(self.cashier, category=Category.STOCK).exists())

    def test_purchase_and_expense_notify_owner_but_not_the_actor(self):
        self.run_commit(self.purchase, [(InventoryItem.objects.get(variation=self.k10), "5", "100")], user=self.manager)
        self.assertTrue(self.notes(self.owner, category=Category.PURCHASES).exists())
        self.assertFalse(self.notes(self.manager, category=Category.PURCHASES).exists())
        from apps.finance import services as finance

        self.run_commit(finance.record_expense, self.manager, uuid.uuid4(), category=self.transport,
                        expense_date=self.today(), amount=D("500"), payment_method="CASH", description="Fuel")
        self.assertTrue(self.notes(self.owner, category=Category.FINANCE).exists())
        self.run_commit(self.expense, "100")   # recorded by the Owner: nobody else with finance access
        self.assertEqual(self.notes(self.owner, category=Category.FINANCE).count(), 1)

    def test_pos_events(self):
        shift = self.open()
        bank = self.run_commit(self.sell, method="BANK_TRANSFER")
        note = self.notes(self.manager, category=Category.PAYMENTS).get()
        self.assertEqual(note.url, reverse("pos:sale_detail", args=[bank.number]))
        sale = self.sell()
        self.run_commit(pos.refund_sale, sale, self.manager, "Damaged", drawer_shift=shift)
        self.assertTrue(self.notes(self.owner, category=Category.POS, title__contains="voided").exists())
        self.run_commit(pos.close_shift, shift, self.cashier, D("900"), "Short")
        self.assertTrue(self.notes(self.manager, category=Category.POS, title__contains="short").exists())
        self.assertFalse(self.notes(self.cashier, category=Category.POS).exists())


class InboxViewTests(NotifyTestCase):
    def setUp(self):
        super().setUp()
        self.order = self.run_commit(self.place)
        self.other = make_user(username="other@example.com")

    def test_customer_sees_only_own(self):
        self.login(self.customer)
        response = self.client.get(reverse("notifications:list"))
        self.assertContains(response, self.order.number)
        self.assertTemplateUsed(response, "notifications/customer_list.html")
        manager_note = self.notes(self.manager).get()
        self.assertEqual(self.client.get(reverse("notifications:open", args=[manager_note.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("notifications:read", args=[manager_note.pk])).status_code, 302)
        manager_note.refresh_from_db()
        self.assertFalse(manager_note.is_read)
        self.login(self.other)
        self.assertNotContains(self.client.get(reverse("notifications:list")), self.order.number)

    def test_open_marks_read_and_redirects(self):
        note = self.notes(self.customer).get()
        self.login(self.customer)
        response = self.client.get(reverse("notifications:open", args=[note.pk]))
        self.assertRedirects(response, note.url, fetch_redirect_response=False)
        note.refresh_from_db()
        self.assertTrue(note.is_read)
        self.client.post(reverse("notifications:read", args=[note.pk]), {"unread": "1"})
        note.refresh_from_db()
        self.assertFalse(note.is_read)
        self.client.post(reverse("notifications:read_all"))
        self.assertEqual(services.unread_count(self.customer), 0)

    def test_bell_and_badges(self):
        self.login(self.manager)
        page = self.client.get(reverse("orders:staff_list"))
        self.assertContains(page, "leo-bell__count")
        self.assertContains(page, self.order.number)
        self.login(self.customer)
        page = self.client.get(reverse("shop:home"))
        self.assertContains(page, "leo-bell--navbar")
        self.client.logout()
        self.assertNotContains(self.client.get(reverse("shop:home")), "leo-bell")

    def test_filters_and_anonymous(self):
        self.login(self.manager)
        response = self.client.get(reverse("notifications:list") + "?show=unread&category=ORDERS")
        self.assertEqual(len(response.context["page_obj"].object_list), 1)
        response = self.client.get(reverse("notifications:list") + "?category=STOCK")
        self.assertEqual(len(response.context["page_obj"].object_list), 0)
        self.client.logout()
        self.assertEqual(self.client.get(reverse("notifications:list")).status_code, 302)

    def test_preferences(self):
        self.login(self.manager)
        form = self.client.get(reverse("notifications:preferences")).context["form"]
        self.assertNotIn("email_order_updates", form.fields)
        offered = dict(form.fields["categories"].choices)
        self.assertIn(Category.STOCK, offered)
        self.assertNotIn(Category.FINANCE, offered)   # managers don't get finance notifications
        self.client.post(reverse("notifications:preferences"), {"categories": [Category.STOCK]})
        pref = services.preference_for(self.manager)
        self.assertIn(Category.ORDERS, pref.muted_categories)
        self.assertNotIn(Category.STOCK, pref.muted_categories)
        self.login(self.customer)
        self.client.post(reverse("notifications:preferences"), {"categories": [Category.ORDERS, Category.PAYMENTS]})
        pref = services.preference_for(self.customer)
        self.assertFalse(pref.email_order_updates)
        self.assertEqual(pref.muted_categories, [Category.REVIEWS])


class AlertTests(NotifyTestCase):
    def test_alerts_by_role(self):
        old = self.place()
        Order.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=5))
        bank = self.place(method=PM.BANK_TRANSFER)
        payments.submit_bank_transfer(bank, self.customer, "REF", slip())
        InventoryItem.objects.filter(variation=self.g25).update(reorder_level=D("5"))
        codes = {a.code: a for a in business_alerts(self.owner)}
        self.assertEqual(codes["pending_orders"].level, "danger")
        self.assertEqual(codes["pending_orders"].count, 2)
        self.assertEqual(codes["unpaid_orders"].count, 1)
        self.assertEqual(codes["transfers"].count, 1)
        self.assertEqual(codes["low_stock"].count, 1)
        self.assertEqual(codes["out_of_stock"].count, 1)   # Black Tea 400g has no stock
        self.assertIn("missing_costs", codes)
        manager_codes = {a.code for a in business_alerts(self.manager)}
        self.assertNotIn("missing_costs", manager_codes)
        self.assertEqual({a.code for a in business_alerts(self.it_admin)}, set())
        self.assertEqual({a.code for a in business_alerts(self.cashier)}, set())

    def test_open_shift_alerts(self):
        shift = self.open()
        type(shift).objects.filter(pk=shift.pk).update(opened_at=timezone.now() - timedelta(hours=20))
        self.assertIn("own_shift", {a.code for a in business_alerts(self.cashier)})
        self.assertIn("open_shifts", {a.code for a in business_alerts(self.manager)})
        config = AlertSettings.load()
        config.open_shift_hours = 48
        config.save()
        self.assertNotIn("open_shifts", {a.code for a in business_alerts(self.manager)})

    def test_pages_and_settings(self):
        self.place()
        self.login(self.manager)
        self.assertContains(self.client.get(reverse("notifications:alerts")), "Orders waiting to be confirmed")
        self.assertContains(self.client.get(reverse("dashboard:manager")), "Needs attention")
        self.assertEqual(self.client.get(reverse("notifications:alert_settings")).status_code, 403)
        self.login(self.customer)
        self.assertEqual(self.client.get(reverse("notifications:alerts")).status_code, 403)
        self.login(self.owner)
        self.client.post(reverse("notifications:alert_settings"), {"pending_order_hours": "6", "unpaid_order_days": "2",
                                                                    "open_shift_hours": "12"})
        config = AlertSettings.load()
        self.assertEqual((config.pending_order_hours, config.reviews_need_approval), (6, False))

    def test_daily_alert_command_runs_once_per_day(self):
        self.place()
        for _ in range(2):
            with self.captureOnCommitCallbacks(execute=True):
                call_command("send_business_alerts", stdout=StringIO())
        alerts = self.notes(self.manager, category=Category.ALERTS)
        self.assertTrue(alerts.exists())
        self.assertEqual(alerts.count(), alerts.values("dedupe_key").distinct().count())
        self.assertFalse(self.notes(self.customer, category=Category.ALERTS).exists())
