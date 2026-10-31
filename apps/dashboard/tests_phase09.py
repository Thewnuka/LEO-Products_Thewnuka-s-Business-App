from django.urls import reverse

from apps.accounts.tests.helpers import PASSWORD
from apps.finance.tests.helpers import FinanceTestCase


class SearchTests(FinanceTestCase):
    def setUp(self):
        super().setUp()
        self.online = self.place()
        self.open()
        self.mine = self.sell()
        self.open(self.cashier2)
        self.theirs = self.sell(user=self.cashier2)
        self.expense("750", description="Delivery van fuel")

    def search(self, user, q):
        self.client.login(username=user.username, password=PASSWORD)
        return self.client.get(reverse("dashboard:search"), {"q": q})

    def test_results_follow_permissions(self):
        response = self.search(self.manager, self.online.number)
        self.assertContains(response, self.online.number)
        response = self.search(self.cashier, "POS-")
        self.assertContains(response, self.mine.number)
        self.assertNotContains(response, self.theirs.number)
        response = self.search(self.cashier, "van fuel")
        self.assertNotContains(response, "Delivery van fuel")         # cashiers can't see expenses
        self.assertContains(self.search(self.manager, "van fuel"), "Delivery van fuel")
        response = self.search(self.it_admin, self.online.number)
        self.assertEqual(response.context["groups"], [])                # IT admin: no orders or payments
        self.assertContains(self.search(self.it_admin, "cashier"), "Staff accounts")
        self.assertContains(self.search(self.owner, "Black"), "Black Tea")

    def test_short_query_and_access(self):
        self.assertContains(self.search(self.owner, "x"), "at least 2 characters")
        self.client.login(username="customer@example.com", password=PASSWORD)
        self.assertEqual(self.client.get(reverse("dashboard:search"), {"q": "LEO"}).status_code, 403)


class ActivityTests(FinanceTestCase):
    def setUp(self):
        super().setUp()
        self.order = self.place()
        self.expense("300")
        self.url = reverse("dashboard:activity")

    def entries(self, user, **params):
        self.client.login(username=user.username, password=PASSWORD)
        response = self.client.get(self.url, params)
        self.assertEqual(response.status_code, 200)
        return response.context["page_obj"].paginator.object_list

    def test_manager_sees_operations_only(self):
        sources = {e.source for e in self.entries(self.manager)}
        self.assertIn("orders", sources)
        self.assertIn("stock", sources)
        self.assertNotIn("finance", sources)
        self.assertNotIn("accounts", sources)
        self.assertEqual(self.entries(self.manager, source="finance"), self.entries(self.manager))  # ignored filter

    def test_owner_sees_finance_and_filters(self):
        self.assertIn("finance", {e.source for e in self.entries(self.owner)})
        only_orders = self.entries(self.owner, source="orders")
        self.assertTrue(only_orders)
        self.assertEqual({e.source for e in only_orders}, {"orders"})
        # Only staff can be chosen as "person"; anything else is ignored.
        self.assertEqual(self.entries(self.owner, actor=self.customer.pk), self.entries(self.owner))
        by_manager = self.entries(self.owner, actor=self.manager.pk)
        self.assertTrue(all(e.actor == self.manager for e in by_manager))
        text = self.entries(self.owner, q=self.order.number)
        self.assertTrue(all(self.order.number in (e.title + e.detail) for e in text))

    def test_access(self):
        for user in (self.cashier, self.it_admin, self.customer):
            self.client.login(username=user.username, password=PASSWORD)
            self.assertEqual(self.client.get(self.url).status_code, 403, user.username)
