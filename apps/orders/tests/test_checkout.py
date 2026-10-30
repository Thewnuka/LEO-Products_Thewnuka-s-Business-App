import uuid
from unittest import mock

from django.core import mail
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.helpers import PASSWORD, make_user
from apps.inventory.models import StockMovement
from apps.orders import services
from apps.orders.models import CheckoutSettings, Order, OrderItem
from apps.payments.models import Payment
from apps.shop import services as shop

from .helpers import PM, D, F, OrdersTestCase, St


class PlaceOrderServiceTests(OrdersTestCase):
    def test_pickup_order_totals_snapshot_and_payment(self):
        order = self.place()
        self.assertTrue(order.number.startswith(f"LEO-{timezone.localdate():%Y}-"))
        self.assertEqual((order.subtotal, order.delivery_fee, order.total), (D("1300"), D("0"), D("1300")))
        self.assertEqual(order.status, St.PENDING)
        self.assertEqual(order.payment_status, Order.PaymentStatus.PENDING)
        self.assertEqual(order.email, self.customer.email)
        item = order.items.get(variation=self.b200)
        self.assertEqual((item.product_name, item.unit_price, item.quantity, item.line_total),
                         ("Black Tea", D("500"), 2, D("1000")))
        self.assertEqual(item.variation_name, self.b200.display_name)
        self.assertEqual(item.sku, self.b200.sku)
        payment = order.payments.get()
        self.assertEqual((payment.method, payment.amount, payment.status), (PM.CASH, D("1300"), Payment.Status.PENDING))
        self.assertEqual(order.events.get().to_status, St.PENDING)

    def test_delivery_fee_and_free_delivery_threshold(self):
        order = self.place(fulfilment=F.DELIVERY)
        self.assertEqual((order.delivery_fee, order.total), (D("350"), D("1650")))
        self.assertEqual(order.delivery_zone_name, "Colombo")
        self.assertEqual(order.address_line1, "12 Galle Road")
        big = self.place(fulfilment=F.DELIVERY, lines=[(self.b200, 8), (self.k10, 4)])  # 4,000 + 1,200
        self.assertEqual((big.subtotal, big.delivery_fee, big.total), (D("5200"), D("0"), D("5200")))

    def test_pickup_never_has_delivery_fee_or_address(self):
        order = self.place(fulfilment=F.PICKUP, delivery_zone=self.colombo, address_line1="ignored", city="ignored")
        self.assertEqual(order.delivery_fee, D("0"))
        self.assertIsNone(order.delivery_zone)
        self.assertEqual(order.address_line1, "")

    def test_order_numbers_are_sequential_and_unique(self):
        first, second = self.place(), self.place()
        self.assertNotEqual(first.number, second.number)
        self.assertEqual(int(second.number.rsplit("-", 1)[1]), int(first.number.rsplit("-", 1)[1]) + 1)

    def test_order_number_clash_is_retried(self):
        first = self.place()
        self.fill_cart()
        with mock.patch("apps.orders.services.next_order_number", side_effect=[first.number, "LEO-2026-99999"]):
            order, created = services.place_order(self.customer, self.details(), uuid.uuid4())
        self.assertTrue(created)
        self.assertEqual(order.number, "LEO-2026-99999")
        self.assertEqual(self.stock(self.b200), D("6"))  # the failed attempt deducted nothing

    def test_stock_deducted_once_with_ledger_entries_and_cart_emptied(self):
        order = self.place()
        self.assertEqual(self.stock(self.b200), D("8"))
        self.assertEqual(self.stock(self.k10), D("19"))
        sales = StockMovement.objects.filter(order_item__order=order, movement_type=StockMovement.Type.SALE)
        self.assertEqual(sales.count(), 2)
        self.assertFalse(shop.get_cart_for_user(self.customer).items.exists())

    def test_same_checkout_token_returns_the_first_order(self):
        self.fill_cart()
        token = uuid.uuid4()
        first, created = services.place_order(self.customer, self.details(), token)
        self.fill_cart()
        again, created_again = services.place_order(self.customer, self.details(), token)
        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(first.pk, again.pk)
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(self.stock(self.b200), D("8"))  # deducted once

    def test_overselling_is_refused_and_nothing_is_saved(self):
        self.fill_cart(lines=[(self.g25, 3)])
        # Someone else buys the stock after this customer filled their cart.
        other = make_user(username="other@example.com")
        self.place(user=other, lines=[(self.g25, 2)])
        with self.assertRaises(ValidationError):
            services.place_order(self.customer, self.details(), uuid.uuid4())
        self.assertEqual(Order.objects.filter(customer=self.customer).count(), 0)
        self.assertEqual(self.stock(self.g25), D("1"))
        self.assertTrue(shop.get_cart_for_user(self.customer).items.exists())  # cart kept

    def test_last_item_race_with_stale_quote(self):
        # Simulate two requests that both checked stock before either deducted it:
        # the conditional update in the stock ledger must stop the second sale.
        other = make_user(username="other@example.com")
        cart = self.fill_cart(lines=[(self.g25, 3)])
        stale_quote = services.quote(cart, F.PICKUP)
        self.fill_cart(other, lines=[(self.g25, 3)])
        services.place_order(other, self.details(), uuid.uuid4())
        with mock.patch("apps.orders.services.quote", return_value=stale_quote):
            with self.assertRaises(ValidationError) as ctx:
                services.place_order(self.customer, self.details(), uuid.uuid4())
        self.assertIn("only 0", str(ctx.exception))
        self.assertEqual(self.stock(self.g25), D("0"))
        self.assertEqual(OrderItem.objects.filter(variation=self.g25).count(), 1)
        self.assertEqual(Order.objects.filter(customer=self.customer).count(), 0)

    def test_changed_total_is_refused(self):
        self.fill_cart()
        with self.assertRaises(ValidationError) as ctx:
            services.place_order(self.customer, self.details(), uuid.uuid4(), expected_total=D("1000"))
        self.assertEqual(ctx.exception.code, "total_changed")
        self.assertFalse(Order.objects.exists())

    def test_empty_cart_is_refused(self):
        with self.assertRaises(ValidationError):
            services.place_order(self.customer, self.details(), uuid.uuid4())

    def test_inactive_zone_and_disabled_options_are_refused(self):
        self.fill_cart()
        with self.assertRaises(ValidationError):
            services.place_order(self.customer, self.details(F.DELIVERY, delivery_zone=self.kandy), uuid.uuid4())
        config = CheckoutSettings.load()
        config.cash_on_pickup_enabled = False
        config.save()
        with self.assertRaises(ValidationError):
            services.place_order(self.customer, self.details(F.PICKUP, PM.CASH), uuid.uuid4())
        with self.assertRaises(ValidationError):  # no gateway configured
            services.place_order(self.customer, self.details(F.PICKUP, PM.ONLINE), uuid.uuid4())
        self.assertFalse(Order.objects.exists())

    def test_delivery_not_offered_without_active_zones(self):
        self.colombo.is_active = False
        self.colombo.save()
        self.assertEqual(services.fulfilment_options(), [F.PICKUP])

    def test_price_snapshot_survives_catalogue_changes(self):
        order = self.place()
        self.b200.selling_price = D("750")
        self.b200.save()
        item = order.items.get(variation=self.b200)
        item.refresh_from_db()
        self.assertEqual(item.unit_price, D("500"))
        order.refresh_from_db()
        self.assertEqual(order.total, D("1300"))

    def test_confirmation_email_sent_after_commit(self):
        with self.captureOnCommitCallbacks(execute=True):
            order = self.place()
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(order.number, mail.outbox[0].subject)
        self.assertEqual(mail.outbox[0].to, [self.customer.email])


class CheckoutViewTests(OrdersTestCase):
    def setUp(self):
        super().setUp()
        self.client.login(username="customer@example.com", password=PASSWORD)

    def post_details(self, **overrides):
        data = {"full_name": "Nimal Perera", "phone": "0771234567", "fulfilment": "DELIVERY",
                "delivery_zone": self.colombo.pk, "address_line1": "12 Galle Road", "city": "Colombo 3",
                "payment_method": "CASH"}
        data.update(overrides)
        return self.client.post(reverse("orders:checkout"), data)

    def test_guest_is_sent_to_sign_in(self):
        self.client.logout()
        response = self.client.get(reverse("orders:checkout"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:customer_login"), response["Location"])

    def test_staff_cannot_check_out(self):
        self.client.login(username="manager", password=PASSWORD)
        self.assertEqual(self.client.get(reverse("orders:checkout")).status_code, 403)

    def test_empty_cart_redirects_to_cart(self):
        self.assertRedirects(self.client.get(reverse("orders:checkout")), reverse("shop:cart"))

    def test_details_form_validation(self):
        self.fill_cart()
        response = self.post_details(address_line1="", city="", phone="abc")
        self.assertEqual(response.status_code, 200)
        form = response.context["form"]
        self.assertIn("address_line1", form.errors)
        self.assertIn("city", form.errors)
        self.assertIn("phone", form.errors)
        response = self.post_details(delivery_zone=self.kandy.pk)  # inactive zone
        self.assertIn("delivery_zone", response.context["form"].errors)
        response = self.post_details(payment_method="ONLINE")
        self.assertIn("payment_method", response.context["form"].errors)

    def test_full_checkout_flow(self):
        self.fill_cart()
        self.assertContains(self.client.get(reverse("shop:cart")), reverse("orders:checkout"))
        self.assertRedirects(self.post_details(), reverse("orders:checkout_review"))
        review = self.client.get(reverse("orders:checkout_review"))
        self.assertContains(review, "1,650.00")
        self.assertContains(review, "12 Galle Road")
        token = self.client.session["checkout"]["token"]
        response = self.client.post(reverse("orders:checkout_review"), {"token": token})
        order = Order.objects.get()
        self.assertRedirects(response, f"{reverse('orders:detail', args=[order.number])}?placed=1")
        self.assertEqual(order.total, D("1650"))
        page = self.client.get(response["Location"])
        self.assertContains(page, "your order is placed")
        self.assertContains(page, order.number)

    def test_double_submit_creates_one_order(self):
        self.fill_cart()
        self.post_details()
        token = self.client.session["checkout"]["token"]
        self.client.post(reverse("orders:checkout_review"), {"token": token})
        response = self.client.post(reverse("orders:checkout_review"), {"token": token})
        order = Order.objects.get()
        self.assertRedirects(response, order.get_absolute_url())
        self.assertEqual(self.stock(self.b200), D("8"))

    def test_total_posted_by_browser_is_ignored(self):
        self.fill_cart()
        self.post_details()
        token = self.client.session["checkout"]["token"]
        self.client.post(reverse("orders:checkout_review"), {"token": token, "total": "1", "subtotal": "1"})
        self.assertEqual(Order.objects.get().total, D("1650"))

    def test_price_change_after_review_asks_to_review_again(self):
        self.fill_cart()
        self.post_details()
        self.b200.selling_price = D("600")
        self.b200.save()
        token = self.client.session["checkout"]["token"]
        response = self.client.post(reverse("orders:checkout_review"), {"token": token})
        self.assertRedirects(response, reverse("orders:checkout_review"), fetch_redirect_response=False)
        self.assertFalse(Order.objects.exists())
        # Second attempt with the updated total succeeds.
        self.client.post(reverse("orders:checkout_review"), {"token": token})
        self.assertEqual(Order.objects.get().total, D("1850"))

    def test_wrong_token_does_not_place_order(self):
        self.fill_cart()
        self.post_details()
        self.client.post(reverse("orders:checkout_review"), {"token": str(uuid.uuid4())})
        self.assertFalse(Order.objects.exists())

    def test_review_post_requires_csrf(self):
        from django.test import Client

        client = Client(enforce_csrf_checks=True)
        client.login(username="customer@example.com", password=PASSWORD)
        self.assertEqual(client.post(reverse("orders:checkout_review"), {"token": "x"}).status_code, 403)
