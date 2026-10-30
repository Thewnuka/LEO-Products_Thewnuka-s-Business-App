from django.core import mail
from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.accounts.tests.helpers import PASSWORD, make_user
from apps.inventory.models import StockMovement
from apps.orders import services
from apps.orders.models import Order, OrderItem, OrderStatusEvent
from apps.payments import services as payments
from apps.payments.models import Payment

from .helpers import PM, D, F, OrdersTestCase, St, slip


class StatusWorkflowTests(OrdersTestCase):
    def test_pickup_cash_order_full_lifecycle(self):
        order = self.place(fulfilment=F.PICKUP, method=PM.CASH)
        for status in (St.CONFIRMED, St.PROCESSING, St.READY_FOR_PICKUP):
            order = services.change_status(order, status, self.manager)
        with self.assertRaises(ValidationError):  # cash not recorded yet
            services.change_status(order, St.COMPLETED, self.manager)
        payments.record_cash_payment(order, self.cashier)
        order = services.change_status(order, St.COMPLETED, self.manager)
        self.assertEqual(order.status, St.COMPLETED)
        self.assertIsNotNone(order.confirmed_at)
        self.assertIsNotNone(order.ready_at)
        self.assertIsNotNone(order.completed_at)
        self.assertEqual(list(order.events.values_list("to_status", flat=True)),
                         [St.PENDING, St.CONFIRMED, St.PROCESSING, St.READY_FOR_PICKUP, St.COMPLETED])
        self.assertEqual(order.events.last().created_by, self.manager)

    def test_delivery_order_path(self):
        order = self.place(fulfilment=F.DELIVERY, method=PM.CASH)
        for status in (St.CONFIRMED, St.PROCESSING, St.OUT_FOR_DELIVERY, St.DELIVERED):
            order = services.change_status(order, status, self.manager)
        self.assertIsNotNone(order.dispatched_at)
        self.assertIsNotNone(order.delivered_at)

    def test_invalid_transitions_are_refused(self):
        pickup = self.place(fulfilment=F.PICKUP)
        delivery = self.place(fulfilment=F.DELIVERY)
        for order, status in ((pickup, St.COMPLETED), (pickup, St.PROCESSING), (pickup, St.DELIVERED)):
            with self.assertRaises(ValidationError):
                services.change_status(order, status, self.manager)
        for status in (St.CONFIRMED, St.PROCESSING):
            pickup = services.change_status(pickup, status, self.manager)
            delivery = services.change_status(delivery, status, self.manager)
        with self.assertRaises(ValidationError):
            services.change_status(pickup, St.OUT_FOR_DELIVERY, self.manager)
        with self.assertRaises(ValidationError):
            services.change_status(delivery, St.READY_FOR_PICKUP, self.manager)
        pickup.refresh_from_db()
        self.assertEqual(pickup.status, St.PROCESSING)

    def test_bank_transfer_order_confirmed_only_after_payment(self):
        order = self.place(method=PM.BANK_TRANSFER)
        self.assertNotIn(St.CONFIRMED, services.allowed_transitions(order))
        with self.assertRaises(ValidationError):
            services.change_status(order, St.CONFIRMED, self.manager)
        payment = payments.submit_bank_transfer(order, self.customer, "TRX-1", slip())
        payments.review_bank_transfer(payment, self.manager, approve=True)
        order.refresh_from_db()
        self.assertIn(St.CONFIRMED, services.allowed_transitions(order))
        services.change_status(order, St.CONFIRMED, self.manager)

    def test_completed_and_cancelled_are_final(self):
        order = self.place()
        services.cancel_order(order, self.manager, "Out of stock")
        order.refresh_from_db()
        self.assertEqual(services.allowed_transitions(order), [])
        with self.assertRaises(ValidationError):
            services.change_status(order, St.CONFIRMED, self.manager)

    def test_status_email_sent(self):
        order = self.place()
        mail.outbox.clear()
        with self.captureOnCommitCallbacks(execute=True):
            services.change_status(order, St.CONFIRMED, self.manager)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Confirmed", mail.outbox[0].subject)


class CancellationTests(OrdersTestCase):
    def test_cancel_restores_stock_once(self):
        order = self.place()
        self.assertEqual(self.stock(self.b200), D("8"))
        with self.captureOnCommitCallbacks(execute=True):
            order = services.cancel_order(order, self.manager, "Customer called")
        self.assertEqual(order.status, St.CANCELLED)
        self.assertTrue(order.stock_restored)
        self.assertEqual(order.cancelled_by, self.manager)
        self.assertEqual(self.stock(self.b200), D("10"))
        self.assertEqual(self.stock(self.k10), D("20"))
        restocks = StockMovement.objects.filter(order_item__order=order, movement_type=StockMovement.Type.ORDER_CANCEL)
        self.assertEqual(restocks.count(), 2)
        self.assertIn("cancelled", mail.outbox[-1].subject)
        with self.assertRaises(ValidationError):  # second cancel refused, no double restock
            services.cancel_order(order, self.manager, "Again")
        self.assertEqual(self.stock(self.b200), D("10"))
        self.assertEqual(restocks.count(), 2)

    def test_cancel_closes_open_payment(self):
        order = self.place(method=PM.BANK_TRANSFER)
        services.cancel_order(order, self.manager, "Duplicate order")
        self.assertEqual(order.payments.get().status, Payment.Status.FAILED)

    def test_cancel_after_payment_marks_refund_due(self):
        order = self.place()
        payments.record_cash_payment(order, self.cashier)
        order = services.cancel_order(order, self.manager, "Could not deliver")
        self.assertEqual(order.payment_status, Order.PaymentStatus.REFUND_DUE)

    def test_delivered_order_cannot_be_cancelled(self):
        order = self.place(fulfilment=F.DELIVERY)
        for status in (St.CONFIRMED, St.PROCESSING, St.OUT_FOR_DELIVERY, St.DELIVERED):
            order = services.change_status(order, status, self.manager)
        with self.assertRaises(ValidationError):
            services.cancel_order(order, self.manager, "Too late")
        self.assertEqual(self.stock(self.b200), D("8"))

    def test_reason_required(self):
        order = self.place()
        with self.assertRaises(ValidationError):
            services.cancel_order(order, self.manager, "  ")

    def test_customer_can_cancel_only_pending_unpaid(self):
        order = self.place()
        self.assertTrue(services.customer_can_cancel(order))
        services.change_status(order, St.CONFIRMED, self.manager)
        with self.assertRaises(ValidationError):
            services.cancel_order(order, self.customer, "Changed my mind", by_customer=True)
        order2 = self.place(method=PM.BANK_TRANSFER)
        payments.submit_bank_transfer(order2, self.customer, "TRX", slip())
        order2.refresh_from_db()
        self.assertFalse(services.customer_can_cancel(order2))


class DataProtectionTests(OrdersTestCase):
    def test_orders_cannot_be_deleted(self):
        from django.db import transaction
        from django.db.models import ProtectedError

        order = self.place()
        for obj in (order, order.items.first(), order.events.first()):
            with self.assertRaises((ValidationError, ProtectedError)), transaction.atomic():
                obj.delete()
        self.assertTrue(Order.objects.filter(pk=order.pk).exists())

    def test_ordered_variation_cannot_be_deleted(self):
        from django.db.models import ProtectedError

        order = self.place()
        with self.assertRaises(ProtectedError):
            self.k10.delete()
        self.assertTrue(OrderItem.objects.filter(order=order, variation=self.k10).exists())


class CustomerOrderPageTests(OrdersTestCase):
    def setUp(self):
        super().setUp()
        self.order = self.place()
        self.other = make_user(username="other@example.com")
        self.other_order = self.place(user=self.other)

    def login(self, user="customer@example.com"):
        self.client.login(username=user, password=PASSWORD)

    def test_my_orders_lists_only_own_orders(self):
        self.login()
        response = self.client.get(reverse("orders:my_orders"))
        self.assertContains(response, self.order.number)
        self.assertNotContains(response, self.other_order.number)

    def test_other_customers_order_is_404(self):
        self.login()
        self.assertEqual(self.client.get(reverse("orders:detail", args=[self.other_order.number])).status_code, 404)
        response = self.client.post(reverse("orders:cancel", args=[self.other_order.number]), {"reason": "x"})
        self.assertEqual(response.status_code, 404)
        self.other_order.refresh_from_db()
        self.assertEqual(self.other_order.status, St.PENDING)

    def test_order_detail_shows_status_payment_and_items(self):
        self.login()
        response = self.client.get(reverse("orders:detail", args=[self.order.number]))
        self.assertContains(response, "Black Tea")
        self.assertContains(response, "1,300.00")
        self.assertContains(response, "Awaiting payment")
        self.assertContains(response, "Cancel this order")

    def test_customer_cancel_via_page(self):
        self.login()
        response = self.client.post(reverse("orders:cancel", args=[self.order.number]), {"reason": "Ordered twice"})
        self.assertRedirects(response, self.order.get_absolute_url())
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, St.CANCELLED)
        self.assertEqual(self.stock(self.b200), D("8"))  # 2 restored, other customer's 2 still sold

    def test_customer_cannot_use_staff_actions(self):
        self.login()
        urls = [reverse("orders:staff_list"), reverse("orders:staff_detail", args=[self.order.number])]
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 403)
        posts = [(reverse("orders:staff_status", args=[self.order.number]), {"to_status": "CONFIRMED"}),
                 (reverse("orders:staff_cancel", args=[self.order.number]), {"reason": "x"}),
                 (reverse("payments:record_cash", args=[self.order.number]), {})]
        for url, data in posts:
            self.assertEqual(self.client.post(url, data).status_code, 403)
        self.order.refresh_from_db()
        self.assertEqual((self.order.status, self.order.payment_status), (St.PENDING, Order.PaymentStatus.PENDING))

    def test_customer_home_shows_recent_orders(self):
        self.login()
        self.assertContains(self.client.get(reverse("accounts:customer_home")), self.order.number)

    def test_my_orders_requires_login(self):
        response = self.client.get(reverse("orders:my_orders"))
        self.assertEqual(response.status_code, 302)


class StaffOrderPageTests(OrdersTestCase):
    def setUp(self):
        super().setUp()
        self.order = self.place(fulfilment=F.DELIVERY)
        self.bank_order = self.place(method=PM.BANK_TRANSFER)

    def login(self, user):
        self.client.login(username=user.username, password=PASSWORD)

    def test_view_permissions_by_role(self):
        url = reverse("orders:staff_list")
        for user, code in ((self.owner, 200), (self.manager, 200), (self.cashier, 200), (self.it_admin, 403)):
            self.login(user)
            self.assertEqual(self.client.get(url).status_code, code, user.role)
            self.assertEqual(self.client.get(reverse("orders:staff_detail", args=[self.order.number])).status_code,
                             code, user.role)

    def test_search_and_filters(self):
        self.login(self.manager)
        url = reverse("orders:staff_list")
        response = self.client.get(url, {"payment_method": "BANK_TRANSFER"})
        self.assertContains(response, self.bank_order.number)
        self.assertNotContains(response, self.order.number)
        response = self.client.get(url, {"q": self.order.number})
        self.assertContains(response, self.order.number)
        self.assertNotContains(response, self.bank_order.number)
        services.change_status(self.order, St.CONFIRMED, self.manager)
        response = self.client.get(url, {"status": "CONFIRMED"})
        self.assertContains(response, self.order.number)
        self.assertNotContains(response, self.bank_order.number)
        response = self.client.get(url, {"payment_status": "PENDING", "date_from": "2000-01-01", "date_to": "2000-01-02"})
        self.assertContains(response, "No orders found")

    def test_manager_updates_status(self):
        self.login(self.manager)
        url = reverse("orders:staff_status", args=[self.order.number])
        self.assertRedirects(self.client.post(url, {"to_status": "CONFIRMED", "note": "Called customer"}),
                             reverse("orders:staff_detail", args=[self.order.number]))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, St.CONFIRMED)
        self.assertEqual(OrderStatusEvent.objects.filter(order=self.order).last().note, "Called customer")
        # An invalid jump is refused with a message.
        self.client.post(url, {"to_status": "COMPLETED"})
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, St.CONFIRMED)

    def test_cancel_through_status_form_is_refused(self):
        self.login(self.manager)
        self.client.post(reverse("orders:staff_status", args=[self.order.number]), {"to_status": "CANCELLED"})
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, St.PENDING)

    def test_cashier_cannot_change_status_or_cancel(self):
        self.login(self.cashier)
        self.assertEqual(self.client.post(reverse("orders:staff_status", args=[self.order.number]),
                                          {"to_status": "CONFIRMED"}).status_code, 403)
        self.assertEqual(self.client.post(reverse("orders:staff_cancel", args=[self.order.number]),
                                          {"reason": "x"}).status_code, 403)
        response = self.client.get(reverse("orders:staff_detail", args=[self.order.number]))
        self.assertNotContains(response, reverse("orders:staff_status", args=[self.order.number]))
        self.assertContains(response, reverse("payments:record_cash", args=[self.order.number]))

    def test_manager_cancels_with_reason(self):
        self.login(self.manager)
        self.client.post(reverse("orders:staff_cancel", args=[self.order.number]), {"reason": "No rider available"})
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, St.CANCELLED)
        self.assertEqual(self.order.cancel_reason, "No rider available")

    def test_detail_shows_history_and_stock_movements(self):
        self.login(self.owner)
        response = self.client.get(reverse("orders:staff_detail", args=[self.order.number]))
        self.assertContains(response, "Online order")
        self.assertContains(response, "12 Galle Road")
        self.assertContains(response, "Order placed")

    def test_history_merges_order_and_payment_events_with_labels(self):
        payment = payments.submit_bank_transfer(self.bank_order, self.customer, "REF", slip())
        payments.review_bank_transfer(payment, self.manager, approve=False, note="Slip unreadable")
        self.login(self.manager)
        response = self.client.get(reverse("orders:staff_detail", args=[self.bank_order.number]))
        titles = [h["title"] for h in response.context["history"]]
        self.assertEqual(titles[0], "Pending")
        self.assertIn(f"{payment.reference}: Transfer details submitted", titles)
        self.assertIn(f"{payment.reference}: Transfer rejected", titles)
        self.assertContains(response, "Slip unreadable")
        self.assertContains(response, "Waiting for the customer to pay")

    def test_settings_owner_only(self):
        url = reverse("orders:settings")
        for user, code in ((self.owner, 200), (self.manager, 403), (self.cashier, 403), (self.it_admin, 403)):
            self.login(user)
            self.assertEqual(self.client.get(url).status_code, code, user.role)

    def test_settings_validation_and_zone_management(self):
        self.login(self.owner)
        url = reverse("orders:settings")
        data = {"delivery_enabled": "on", "pickup_enabled": "", "cash_on_delivery_enabled": "on",
                "bank_transfer_enabled": "on", "bank_name": "", "bank_account_name": "", "bank_account_number": ""}
        response = self.client.post(url, data)
        self.assertIn("bank_transfer_enabled", response.context["form"].errors)
        response = self.client.post(url, {"delivery_enabled": "", "pickup_enabled": ""})
        self.assertIn("pickup_enabled", response.context["form"].errors)
        response = self.client.post(reverse("orders:zone_create"), {"name": "Galle", "fee": "450", "sort_order": "2",
                                                                    "is_active": "on"})
        self.assertRedirects(response, url)
        response = self.client.post(reverse("orders:zone_create"), {"name": "Bad", "fee": "-1", "sort_order": "0"})
        self.assertEqual(response.status_code, 200)
        self.colombo.refresh_from_db()
        response = self.client.post(reverse("orders:zone_update", args=[self.colombo.pk]),
                                    {"name": "Colombo", "fee": "500", "sort_order": "0", "is_active": "on"})
        self.assertRedirects(response, url)
        self.order.refresh_from_db()
        self.assertEqual(self.order.delivery_fee, D("350"))  # existing order keeps its fee

    def test_staff_sidebar_shows_orders_by_capability(self):
        self.login(self.cashier)
        response = self.client.get(reverse("orders:staff_list"))
        self.assertContains(response, "Customer orders")
        self.assertNotContains(response, reverse("orders:settings"))
        self.login(self.it_admin)
        response = self.client.get(reverse("accounts:staff_profile"))
        self.assertNotContains(response, reverse("orders:staff_list"))
