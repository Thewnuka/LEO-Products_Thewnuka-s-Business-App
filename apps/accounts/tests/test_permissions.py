"""URL-level access matrix: every protected page checked for every role."""
from django.http import HttpResponse
from django.test import RequestFactory
from django.urls import reverse
from rest_framework.test import APIRequestFactory, force_authenticate
from rest_framework.views import APIView

from apps.accounts.permissions import HasCapability, capability_required
from apps.accounts.roles import Capability

from .helpers import AccountsTestCase


class AccessMatrixTests(AccountsTestCase):
    def assert_status(self, user, url, expected):
        self.client.logout()
        if user:
            self.client.force_login(user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, expected, f"{getattr(user, 'role', 'anonymous')} GET {url}")
        return response

    def test_dashboards(self):
        urls = {name: reverse(f"dashboard:{name}") for name in ("owner", "it_admin", "manager", "cashier")}
        allowed = {
            self.owner: {"owner", "it_admin", "manager", "cashier"},
            self.it_admin: {"it_admin"},
            self.manager: {"manager"},
            self.cashier: {"cashier"},
            self.customer: set(),
        }
        for user, names in allowed.items():
            for name, url in urls.items():
                with self.subTest(role=user.role, dashboard=name):
                    self.assert_status(user, url, 200 if name in names else 403)

    def test_staff_management_pages(self):
        urls = [
            reverse("accounts:staff_list"),
            reverse("accounts:staff_create"),
            reverse("accounts:staff_detail", args=[self.cashier.pk]),
            reverse("accounts:staff_update", args=[self.cashier.pk]),
            reverse("accounts:staff_set_password", args=[self.cashier.pk]),
        ]
        for user in (self.manager, self.cashier, self.customer):
            for url in urls:
                with self.subTest(role=user.role, url=url):
                    self.assert_status(user, url, 403)
        for user in (self.owner, self.it_admin):
            for url in urls:
                with self.subTest(role=user.role, url=url):
                    self.assert_status(user, url, 200)

    def test_anonymous_users_are_sent_to_the_right_login(self):
        for url in (reverse("dashboard:owner"), reverse("accounts:staff_list"), reverse("accounts:staff_profile")):
            with self.subTest(url=url):
                response = self.assert_status(None, url, 302)
                self.assertTrue(response["Location"].startswith(reverse("accounts:staff_login")))
        for url in (reverse("accounts:customer_home"), reverse("accounts:customer_profile")):
            with self.subTest(url=url):
                response = self.assert_status(None, url, 302)
                self.assertTrue(response["Location"].startswith(reverse("accounts:customer_login")))

    def test_customer_portal_is_customers_only(self):
        for user in (self.owner, self.cashier):
            self.assert_status(user, reverse("accounts:customer_home"), 403)
        self.assert_status(self.customer, reverse("accounts:customer_home"), 200)

    def test_staff_profile_is_staff_only(self):
        self.assert_status(self.customer, reverse("accounts:staff_profile"), 403)
        self.assert_status(self.cashier, reverse("accounts:staff_profile"), 200)

    def test_dashboard_router(self):
        expected = {self.owner: "owner", self.it_admin: "it_admin", self.manager: "manager", self.cashier: "cashier"}
        for user, name in expected.items():
            self.client.force_login(user)
            self.assertRedirects(self.client.get(reverse("dashboard:home")), reverse(f"dashboard:{name}"))
        self.assert_status(self.customer, reverse("dashboard:home"), 403)

    def test_django_admin_is_owner_only(self):
        for user in (self.it_admin, self.manager, self.cashier, self.customer):
            with self.subTest(role=user.role):
                response = self.assert_status(user, reverse("admin:index"), 302)
                self.assertIn(reverse("admin:login"), response["Location"])
        self.assert_status(self.owner, reverse("admin:index"), 200)

    def test_403_page_is_branded_and_links_home(self):
        response = self.assert_status(self.cashier, reverse("dashboard:owner"), 403)
        self.assertContains(response, "Access denied", status_code=403)
        self.assertContains(response, reverse("dashboard:cashier"), status_code=403)


class FinanceBoundaryTests(AccountsTestCase):
    """No finance module exists yet, so check the enforcement tools future modules will use."""

    class FinanceApi(APIView):
        permission_classes = [HasCapability]
        required_capability = Capability.MANAGE_FINANCE

        def get(self, request):
            return HttpResponse("ok")

    def test_api_permission_class(self):
        view = self.FinanceApi.as_view()
        for user, expected in ((self.owner, 200), (self.it_admin, 403), (self.manager, 403), (self.cashier, 403), (self.customer, 403)):
            request = APIRequestFactory().get("/")
            force_authenticate(request, user=user)
            with self.subTest(role=user.role):
                self.assertEqual(view(request).status_code, expected)

    def test_function_view_decorator(self):
        from django.core.exceptions import PermissionDenied

        @capability_required(Capability.MANAGE_FINANCE)
        def finance_page(request):
            return HttpResponse("ok")

        request = RequestFactory().get("/")
        request.user = self.it_admin
        with self.assertRaises(PermissionDenied):
            finance_page(request)
        request.user = self.owner
        self.assertEqual(finance_page(request).status_code, 200)
