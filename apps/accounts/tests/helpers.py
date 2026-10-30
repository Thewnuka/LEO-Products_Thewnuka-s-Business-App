from django.core.cache import cache
from django.test import TestCase

from apps.accounts.models import User
from apps.accounts.roles import Role

PASSWORD = "Leo-Test-Pass-2026!"


def make_user(role=Role.CUSTOMER, username=None, password=PASSWORD, **extra):
    username = username or f"{role.lower()}_{User.objects.count() + 1}"
    extra.setdefault("email", f"{username}@example.com")
    extra.setdefault("first_name", username.split("_")[0].title())
    user = User(username=username, role=role, **extra)
    user.set_password(password)
    user.save()
    return user


class AccountsTestCase(TestCase):
    """Creates one user per role and clears the login throttle cache."""

    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user(Role.OWNER, "owner")
        cls.it_admin = make_user(Role.IT_ADMIN, "itadmin")
        cls.manager = make_user(Role.MANAGER, "manager")
        cls.cashier = make_user(Role.CASHIER, "cashier")
        cls.customer = make_user(Role.CUSTOMER, "customer@example.com", email="customer@example.com")

    def setUp(self):
        cache.clear()
