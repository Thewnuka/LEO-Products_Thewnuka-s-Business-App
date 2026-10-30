"""Regression tests for issues found in the Phase 02 security review."""
from django.contrib.auth import SESSION_KEY
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.roles import Role

from .helpers import PASSWORD, AccountsTestCase, make_user


class AdminLoginThrottleTests(AccountsTestCase):
    """The Django admin has its own login form; it must be throttled too."""

    def test_admin_login_is_locked_after_repeated_failures(self):
        url = reverse("admin:login")
        for _ in range(5):
            self.client.post(url, {"username": "owner", "password": "wrong"})
        self.client.post(url, {"username": "owner", "password": PASSWORD})
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_lock_is_shared_between_admin_and_staff_portal(self):
        for _ in range(5):
            self.client.post(reverse("admin:login"), {"username": "owner", "password": "wrong"})
        response = self.client.post(reverse("accounts:staff_login"), {"username": "owner", "password": PASSWORD})
        self.assertContains(response, "Too many failed attempts")

    def test_successful_login_resets_the_counter(self):
        url = reverse("accounts:staff_login")
        for _ in range(4):
            self.client.post(url, {"username": "owner", "password": "wrong"})
        self.client.post(url, {"username": "owner", "password": PASSWORD})
        self.client.logout()
        for _ in range(4):
            self.client.post(url, {"username": "owner", "password": "wrong"})
        self.client.post(url, {"username": "owner", "password": PASSWORD})
        self.assertIn(SESSION_KEY, self.client.session)


class SignInIdentifierCollisionTests(AccountsTestCase):
    """A username must never equal another account's email (and vice versa)."""

    def staff_post(self, **overrides):
        data = {"username": "newstaff", "first_name": "A", "last_name": "B", "email": "newstaff@example.com",
                "phone_number": "", "role": Role.CASHIER, "password1": "Temp-Pass-98765", "password2": "Temp-Pass-98765"}
        data.update(overrides)
        self.client.force_login(self.owner)
        return self.client.post(reverse("accounts:staff_create"), data)

    def test_staff_username_cannot_be_another_users_email(self):
        response = self.staff_post(username="CUSTOMER@example.com")
        self.assertEqual(response.status_code, 200)
        self.assertIn("username", response.context["form"].errors)
        # The customer can still sign in with their email.
        self.client.logout()
        login = self.client.post(reverse("accounts:customer_login"), {"username": "customer@example.com", "password": PASSWORD})
        self.assertRedirects(login, reverse("accounts:customer_home"))

    def test_usernames_are_unique_ignoring_case(self):
        response = self.staff_post(username="OWNER")
        self.assertIn("username", response.context["form"].errors)
        self.assertFalse(User.objects.filter(username="OWNER").exists())

    def test_api_email_cannot_be_another_users_username(self):
        make_user(Role.MANAGER, "boss@example.com", email="real-boss@example.com")
        api = APIClient()
        api.force_authenticate(self.customer)
        response = api.patch(reverse("api:me"), {"email": "BOSS@example.com"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.email, "customer@example.com")

    def test_django_admin_form_also_blocks_collisions(self):
        self.client.force_login(self.owner)
        url = reverse("admin:accounts_user_change", args=[self.cashier.pk])
        page = self.client.get(url)
        data = {k: v for k, v in page.context["adminform"].form.initial.items() if v is not None and k not in ("password", "groups", "user_permissions", "last_login", "date_joined")}
        data.update({"username": "cashier", "email": "customer@example.com", "role": Role.CASHIER, "is_active": "on"})
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 200)  # form redisplayed with an error
        self.cashier.refresh_from_db()
        self.assertNotEqual(self.cashier.email, "customer@example.com")
