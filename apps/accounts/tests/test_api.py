from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.roles import Role

from .helpers import AccountsTestCase

ME = reverse("api:me")


class MeApiTests(AccountsTestCase):
    def setUp(self):
        super().setUp()
        self.api = APIClient()

    def test_requires_sign_in(self):
        self.assertEqual(self.api.get(ME).status_code, 403)

    def test_returns_only_own_safe_fields(self):
        self.api.force_authenticate(self.customer)
        data = self.api.get(ME).json()
        self.assertEqual(data["email"], "customer@example.com")
        self.assertEqual(data["role"], Role.CUSTOMER)
        for secret in ("password", "is_superuser", "is_staff", "user_permissions"):
            self.assertNotIn(secret, data)

    def test_role_cannot_be_changed_through_api(self):
        self.api.force_authenticate(self.customer)
        response = self.api.patch(ME, {"role": Role.OWNER, "is_staff": True, "is_superuser": True, "first_name": "New"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.first_name, "New")
        self.assertEqual(self.customer.role, Role.CUSTOMER)
        self.assertFalse(self.customer.is_staff)

    def test_cannot_take_another_users_email(self):
        self.api.force_authenticate(self.customer)
        response = self.api.patch(ME, {"email": self.owner.email.upper()}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_session_api_requires_csrf_token(self):
        api = APIClient(enforce_csrf_checks=True)
        api.force_login(self.customer)  # real session, not force_authenticate
        response = api.patch(ME, {"first_name": "Hacked"}, format="json")
        self.assertEqual(response.status_code, 403)
        self.customer.refresh_from_db()
        self.assertNotEqual(self.customer.first_name, "Hacked")
