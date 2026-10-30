from django.contrib.auth import SESSION_KEY
from django.test import Client
from django.urls import reverse

from apps.accounts.roles import Role
from apps.accounts.tests.helpers import PASSWORD, make_user
from apps.inventory.models import InventoryItem
from apps.inventory.services import record_movement
from apps.shop.models import Cart, CartItem
from apps.shop.services import SESSION_CART_KEY

from .helpers import D, ShopTestCase

ADD = reverse("shop:cart_add")
CART = reverse("shop:cart")


class CartBasicsTests(ShopTestCase):
    def add(self, variation, qty=1, client=None):
        return (client or self.client).post(ADD, {"variation": variation.pk, "quantity": qty})

    def test_guest_can_add_and_see_totals(self):
        self.assertRedirects(self.add(self.b200, 2), CART)
        self.add(self.k10, 3)
        cart = Cart.objects.get()
        self.assertIsNone(cart.user)
        self.assertEqual(self.client.session[SESSION_CART_KEY], cart.pk)
        r = self.client.get(CART)
        self.assertEqual(r.context["summary"].subtotal, D("1900.00"))  # 2×500 + 3×300
        self.assertContains(r, "LKR 1,900.00")
        self.assertEqual(r.context["cart_count"], 5)  # navbar badge

    def test_adding_twice_combines_lines(self):
        self.add(self.b200, 2)
        self.add(self.b200, 3)
        self.assertEqual(CartItem.objects.get().quantity, 5)

    def test_update_and_remove(self):
        self.add(self.b200, 2)
        item = CartItem.objects.get()
        self.client.post(reverse("shop:cart_update", args=[item.pk]), {"quantity": 4})
        item.refresh_from_db()
        self.assertEqual(item.quantity, 4)
        self.client.post(reverse("shop:cart_update", args=[item.pk]), {"quantity": 0})
        self.assertFalse(CartItem.objects.exists())
        self.add(self.k10)
        item = CartItem.objects.get()
        self.client.post(reverse("shop:cart_remove", args=[item.pk]))
        self.assertFalse(CartItem.objects.exists())
        self.assertContains(self.client.get(CART), "Your cart is empty")

    def test_cart_does_not_touch_inventory(self):
        self.add(self.b200, 5)
        self.assertEqual(InventoryItem.objects.get(variation=self.b200).quantity, D(10))


class StockValidationTests(ShopTestCase):
    def test_cannot_add_more_than_stock(self):
        r = self.client.post(ADD, {"variation": self.g25.pk, "quantity": 4}, follow=True)  # stock 3
        self.assertContains(r, "Only 3 available")
        self.assertFalse(CartItem.objects.exists())
        self.client.post(ADD, {"variation": self.g25.pk, "quantity": 2})
        r = self.client.post(ADD, {"variation": self.g25.pk, "quantity": 2}, follow=True)
        self.assertContains(r, "You already have 2 in your cart")
        self.assertEqual(CartItem.objects.get().quantity, 2)

    def test_cannot_update_above_stock(self):
        self.client.post(ADD, {"variation": self.g25.pk, "quantity": 1})
        item = CartItem.objects.get()
        r = self.client.post(reverse("shop:cart_update", args=[item.pk]), {"quantity": 9}, follow=True)
        self.assertContains(r, "Only 3 available")
        item.refresh_from_db()
        self.assertEqual(item.quantity, 1)

    def test_unavailable_variations_rejected(self):
        for variation in (self.b400, self.b1kg, self.d200):  # out of stock, untracked, draft product
            with self.subTest(variation=variation.sku):
                r = self.client.post(ADD, {"variation": variation.pk, "quantity": 1}, follow=True)
                self.assertContains(r, "not available")
        self.assertFalse(CartItem.objects.exists())

    def test_invalid_input_rejected(self):
        for data in ({"variation": "abc", "quantity": 1}, {"variation": 999999, "quantity": 1},
                     {"variation": self.b200.pk, "quantity": 0}, {"variation": self.b200.pk, "quantity": -3},
                     {"variation": self.b200.pk, "quantity": "1.5"}, {"variation": self.b200.pk, "quantity": 51},
                     {"variation": self.b200.pk}, {}):
            with self.subTest(data=data):
                self.client.post(ADD, data)
        self.assertFalse(CartItem.objects.exists())

    def test_cart_page_reduces_quantity_when_stock_falls(self):
        self.client.post(ADD, {"variation": self.b200.pk, "quantity": 8})
        record_movement(InventoryItem.objects.get(variation=self.b200), "DECREASE", "7", self.owner, reason="shop sale")
        r = self.client.get(CART)
        line = r.context["summary"].lines[0]
        self.assertEqual((line.status, line.item.quantity), ("reduced", 3))
        self.assertContains(r, "only 3 available")
        self.assertEqual(CartItem.objects.get().quantity, 3)

    def test_unavailable_items_flagged_and_excluded_from_total(self):
        self.client.post(ADD, {"variation": self.b200.pk, "quantity": 1})
        self.client.post(ADD, {"variation": self.k10.pk, "quantity": 2})
        self.kokis.status = "INACTIVE"
        self.kokis.save()
        r = self.client.get(CART)
        self.assertEqual(r.context["summary"].total, D("500.00"))
        self.assertContains(r, "No longer available")


class CartOwnershipTests(ShopTestCase):
    def test_customer_cart_is_saved_to_the_account(self):
        self.client.force_login(self.customer)
        self.client.post(ADD, {"variation": self.k10.pk, "quantity": 2})
        cart = Cart.objects.get(user=self.customer)
        self.client.logout()
        self.assertEqual(self.client.get(CART).context["summary"].lines, [])  # guest sees an empty cart
        self.client.force_login(self.customer)
        self.assertEqual(self.client.get(CART).context["summary"].lines[0].item.cart, cart)

    def test_guest_cart_merged_on_sign_in(self):
        self.client.post(ADD, {"variation": self.g25.pk, "quantity": 2})
        user_cart = Cart.objects.create(user=self.customer)
        CartItem.objects.create(cart=user_cart, variation=self.g25, quantity=2)
        CartItem.objects.create(cart=user_cart, variation=self.k10, quantity=1)
        r = self.client.post(reverse("accounts:customer_login"), {"username": "customer@example.com", "password": PASSWORD}, follow=True)
        self.assertContains(r, "We kept the items")
        lines = {i.variation_id: i.quantity for i in CartItem.objects.filter(cart=user_cart)}
        self.assertEqual(lines, {self.g25.pk: 3, self.k10.pk: 1})  # 2+2 capped at stock 3
        self.assertEqual(Cart.objects.filter(user__isnull=True).count(), 0)

    def test_guest_cart_kept_when_registering(self):
        self.client.post(ADD, {"variation": self.k10.pk, "quantity": 4})
        self.client.post(reverse("accounts:register"), {
            "first_name": "New", "last_name": "Buyer", "email": "buyer@example.com", "phone_number": "0771234567",
            "password1": "buyer123", "password2": "buyer123"})
        cart = Cart.objects.get(user__email="buyer@example.com")
        self.assertEqual(cart.items.get().quantity, 4)

    def test_customer_cannot_touch_another_customers_cart(self):
        other = make_user(Role.CUSTOMER, "other@example.com", email="other@example.com")
        other_cart = Cart.objects.create(user=other)
        other_item = CartItem.objects.create(cart=other_cart, variation=self.k10, quantity=2)
        self.client.force_login(self.customer)
        self.client.post(ADD, {"variation": self.b200.pk, "quantity": 1})
        for url, data in ((reverse("shop:cart_update", args=[other_item.pk]), {"quantity": 9}),
                          (reverse("shop:cart_remove", args=[other_item.pk]), {})):
            with self.subTest(url=url):
                self.assertEqual(self.client.post(url, data).status_code, 404)
        other_item.refresh_from_db()
        self.assertEqual(other_item.quantity, 2)
        self.assertNotContains(self.client.get(CART), "Kokis")

    def test_guest_cannot_reach_a_customer_cart_or_another_guest_cart(self):
        user_cart = Cart.objects.create(user=self.customer)
        item = CartItem.objects.create(cart=user_cart, variation=self.k10, quantity=2)
        session = self.client.session
        session[SESSION_CART_KEY] = user_cart.pk  # even if a session pointed at it
        session.save()
        self.assertEqual(self.client.get(CART).context["summary"].lines, [])
        self.assertEqual(self.client.post(reverse("shop:cart_remove", args=[item.pk])).status_code, 404)

        guest_a = Client()
        guest_a.post(ADD, {"variation": self.b200.pk, "quantity": 1})
        a_item = CartItem.objects.get(cart__user__isnull=True)
        guest_b = Client()
        guest_b.post(ADD, {"variation": self.k10.pk, "quantity": 1})
        self.assertEqual(guest_b.post(reverse("shop:cart_update", args=[a_item.pk]), {"quantity": 5}).status_code, 404)
        a_item.refresh_from_db()
        self.assertEqual(a_item.quantity, 1)

    def test_staff_cannot_use_cart(self):
        for staff in (self.owner, self.manager, self.cashier):
            self.client.force_login(staff)
            r = self.client.post(ADD, {"variation": self.b200.pk, "quantity": 1}, follow=True)
            self.assertContains(r, "Staff accounts can")
            self.assertFalse(r.context["show_cart"])
        self.assertFalse(Cart.objects.exists())

    def test_cart_actions_require_post_and_csrf(self):
        self.assertEqual(self.client.get(ADD).status_code, 405)
        csrf_client = Client(enforce_csrf_checks=True)
        self.assertEqual(csrf_client.post(ADD, {"variation": self.b200.pk, "quantity": 1}).status_code, 403)
        self.assertFalse(CartItem.objects.exists())

    def test_next_redirect_cannot_leave_the_site(self):
        r = self.client.post(ADD, {"variation": self.b200.pk, "quantity": 1, "next": "https://evil.example/phish"})
        self.assertRedirects(r, CART)
        r = self.client.post(ADD, {"variation": self.b200.pk, "quantity": 1, "next": reverse("shop:home")})
        self.assertRedirects(r, reverse("shop:home"))

    def test_logout_keeps_customer_cart_but_not_in_guest_session(self):
        self.client.post(reverse("accounts:customer_login"), {"username": "customer@example.com", "password": PASSWORD})
        self.client.post(ADD, {"variation": self.b200.pk, "quantity": 1})
        self.client.post(reverse("accounts:logout"))
        self.assertNotIn(SESSION_KEY, self.client.session)
        self.assertEqual(Cart.objects.get(user=self.customer).items.count(), 1)
