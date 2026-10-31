from django.urls import reverse

from apps.accounts.tests.helpers import PASSWORD, make_user
from apps.notifications.models import AlertSettings, Notification
from apps.orders.tests.helpers import OrdersTestCase
from apps.payments import services as payments
from apps.shop.models import ProductReview, WishlistItem


class WishlistTests(OrdersTestCase):
    def test_customer_toggles_and_lists(self):
        self.client.login(username="customer@example.com", password=PASSWORD)
        url = reverse("shop:wishlist_toggle", args=[self.black.slug])
        self.client.post(url, {"next": "https://evil.example/"})
        self.assertTrue(WishlistItem.objects.filter(user=self.customer, product=self.black).exists())
        page = self.client.get(reverse("shop:wishlist"))
        self.assertContains(page, "Black Tea")
        self.assertContains(self.client.get(reverse("shop:product", args=[self.black.slug])), "Saved to your wishlist")
        response = self.client.post(url, {"next": reverse("shop:wishlist")})
        self.assertRedirects(response, reverse("shop:wishlist"))
        self.assertFalse(WishlistItem.objects.exists())

    def test_only_customers(self):
        url = reverse("shop:wishlist_toggle", args=[self.black.slug])
        self.assertEqual(self.client.post(url).status_code, 302)   # guest -> sign in
        self.client.login(username="manager", password=PASSWORD)
        self.assertEqual(self.client.post(url).status_code, 403)
        self.assertEqual(self.client.get(reverse("shop:wishlist")).status_code, 403)
        self.assertFalse(WishlistItem.objects.exists())

    def test_draft_products_cannot_be_saved(self):
        self.client.login(username="customer@example.com", password=PASSWORD)
        self.assertEqual(self.client.post(reverse("shop:wishlist_toggle", args=[self.draft.slug])).status_code, 404)


class ReviewTests(OrdersTestCase):
    def buy(self, customer=None):
        order = self.place(user=customer, lines=[(self.b200, 1)])
        payments.record_cash_payment(order, self.cashier)
        return order

    def review(self, **data):
        payload = {"rating": "5", "title": "Lovely tea", "body": "Fresh and strong."}
        payload.update(data)
        return self.client.post(reverse("shop:review", args=[self.black.slug]), payload)

    def test_only_buyers_can_review(self):
        self.client.login(username="customer@example.com", password=PASSWORD)
        self.assertRedirects(self.client.get(reverse("shop:review", args=[self.black.slug])),
                             reverse("shop:product", args=[self.black.slug]))
        self.review()
        self.assertFalse(ProductReview.objects.exists())
        self.place(lines=[(self.b200, 1)])           # ordered but not paid
        self.review()
        self.assertFalse(ProductReview.objects.exists())

    def test_review_moderation_flow(self):
        self.buy()
        self.client.login(username="customer@example.com", password=PASSWORD)
        with self.captureOnCommitCallbacks(execute=True):
            self.review()
        review = ProductReview.objects.get()
        self.assertEqual(review.status, ProductReview.Status.PENDING)
        product_page = self.client.get(reverse("shop:product", args=[self.black.slug]))
        self.assertNotContains(product_page, "Fresh and strong.")
        self.assertContains(product_page, "once we've checked it")
        self.assertTrue(Notification.objects.filter(recipient=self.manager, category="REVIEWS").exists())
        self.client.login(username="cashier", password=PASSWORD)
        self.assertEqual(self.client.get(reverse("shop:review_moderation")).status_code, 403)
        self.client.login(username="manager", password=PASSWORD)
        self.client.post(reverse("shop:review_moderate", args=[review.pk]), {"decision": "reject"})  # needs a note
        review.refresh_from_db()
        self.assertEqual(review.status, ProductReview.Status.PENDING)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("shop:review_moderate", args=[review.pk]), {"decision": "approve"})
        review.refresh_from_db()
        self.assertEqual((review.status, review.moderated_by), (ProductReview.Status.APPROVED, self.manager))
        self.assertTrue(Notification.objects.filter(recipient=self.customer, title__contains="published").exists())
        self.client.logout()
        page = self.client.get(reverse("shop:product", args=[self.black.slug]))
        self.assertContains(page, "Fresh and strong.")
        self.assertContains(page, review.display_name)
        self.assertNotContains(page, "customer@example.com")
        self.assertContains(page, "5.0 · 1 review")

    def test_one_review_per_customer_and_edit_resubmits(self):
        self.buy()
        AlertSettings.objects.update_or_create(pk=1, defaults={"reviews_need_approval": False})
        self.client.login(username="customer@example.com", password=PASSWORD)
        self.review()
        review = ProductReview.objects.get()
        self.assertEqual(review.status, ProductReview.Status.APPROVED)   # approval switched off
        AlertSettings.objects.update_or_create(pk=1, defaults={"reviews_need_approval": True})
        self.review(rating="3", title="Changed")
        self.assertEqual(ProductReview.objects.count(), 1)
        review.refresh_from_db()
        self.assertEqual((review.rating, review.title, review.status), (3, "Changed", ProductReview.Status.PENDING))

    def test_invalid_rating_and_other_customer(self):
        self.buy()
        self.client.login(username="customer@example.com", password=PASSWORD)
        response = self.review(rating="9")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(ProductReview.objects.exists())
        make_user(username="other@example.com")
        self.client.login(username="other@example.com", password=PASSWORD)
        self.review()
        self.assertFalse(ProductReview.objects.exists())
