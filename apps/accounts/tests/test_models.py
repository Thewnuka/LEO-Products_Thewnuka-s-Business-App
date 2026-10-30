from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase

from apps.accounts.models import User
from apps.accounts.roles import Capability, Role, can_manage_user, has_capability

from .helpers import PASSWORD, AccountsTestCase, make_user


class CustomUserModelTests(TestCase):
    def test_auth_user_model_is_custom(self):
        self.assertEqual(settings.AUTH_USER_MODEL, "accounts.User")
        self.assertIs(get_user_model(), User)

    def test_create_user_defaults_to_customer(self):
        user = User.objects.create_user(username="tester", password=PASSWORD)
        self.assertTrue(user.check_password(PASSWORD))
        self.assertEqual(user.role, Role.CUSTOMER)
        self.assertFalse(user.is_staff)
        self.assertIsNotNone(user.updated_at)

    def test_create_superuser_is_owner(self):
        admin = User.objects.create_superuser(username="boss", password=PASSWORD)
        self.assertEqual(admin.role, Role.OWNER)
        self.assertTrue(admin.is_staff)
        self.assertTrue(admin.is_superuser)
        self.assertFalse(admin.is_primary_owner)

    def test_password_is_hashed_never_plaintext(self):
        user = make_user()
        self.assertNotIn(PASSWORD, user.password)
        self.assertTrue(user.password.startswith("pbkdf2_sha256$"))

    def test_django_admin_flags_follow_role(self):
        user = make_user(Role.CASHIER, is_staff=True, is_superuser=True)
        user.refresh_from_db()
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        user.role = Role.OWNER
        user.save(update_fields=["role"])
        user.refresh_from_db()
        self.assertTrue(user.is_staff and user.is_superuser)

    def test_email_unique_case_insensitive(self):
        make_user(username="a", email="Same@Example.com")
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_user(username="b", email="same@example.COM")

    def test_blank_emails_allowed_for_several_users(self):
        make_user(username="x", email="")
        make_user(username="y", email="")


class PrimaryOwnerProtectionTests(TestCase):
    def setUp(self):
        self.owner = make_user(Role.OWNER, "admin")
        self.owner.is_primary_owner = True
        self.owner.save()

    def test_cannot_delete(self):
        make_user(Role.CASHIER, "bystander")
        with self.assertRaises(ProtectedError), transaction.atomic():
            self.owner.delete()
        with self.assertRaises(ProtectedError), transaction.atomic():
            User.objects.all().delete()
        # The bulk delete is rolled back as a whole, so nobody was removed.
        self.assertEqual(User.objects.count(), 2)
        self.assertTrue(User.objects.filter(pk=self.owner.pk).exists())

    def test_cannot_demote(self):
        self.owner.role = Role.MANAGER
        with self.assertRaises(ValidationError):
            self.owner.save()

    def test_cannot_deactivate(self):
        self.owner.is_active = False
        with self.assertRaises(ValidationError):
            self.owner.save()

    def test_only_one_primary_owner(self):
        other = make_user(Role.OWNER, "owner2")
        other.is_primary_owner = True
        with self.assertRaises(IntegrityError), transaction.atomic():
            other.save()


class CapabilityTests(AccountsTestCase):
    MONEY = (Capability.MANAGE_FINANCE, Capability.MANAGE_PAYMENTS, Capability.VIEW_ALL_REPORTS)

    def test_owner_has_everything_staff_related(self):
        for cap in self.MONEY + (Capability.MANAGE_STAFF, Capability.MANAGE_BUSINESS_SETTINGS, Capability.USE_POS):
            self.assertTrue(has_capability(self.owner, cap), cap)

    def test_it_admin_has_no_financial_or_business_access(self):
        for cap in self.MONEY + (Capability.MANAGE_BUSINESS_SETTINGS, Capability.USE_POS, Capability.MANAGE_CATALOG):
            self.assertFalse(has_capability(self.it_admin, cap), cap)
        self.assertTrue(has_capability(self.it_admin, Capability.MANAGE_TECHNICAL_SETTINGS))
        self.assertTrue(has_capability(self.it_admin, Capability.MANAGE_STAFF))

    def test_manager_boundaries(self):
        self.assertTrue(has_capability(self.manager, Capability.MANAGE_INVENTORY))
        for cap in self.MONEY + (Capability.MANAGE_STAFF, Capability.VIEW_STAFF, Capability.MANAGE_TECHNICAL_SETTINGS):
            self.assertFalse(has_capability(self.manager, cap), cap)

    def test_cashier_boundaries(self):
        self.assertTrue(has_capability(self.cashier, Capability.USE_POS))
        for cap in self.MONEY + (Capability.MANAGE_STAFF, Capability.MANAGE_TECHNICAL_SETTINGS, Capability.MANAGE_CATALOG):
            self.assertFalse(has_capability(self.cashier, cap), cap)

    def test_customer_only_has_customer_portal(self):
        self.assertTrue(has_capability(self.customer, Capability.USE_CUSTOMER_PORTAL))
        self.assertFalse(has_capability(self.customer, Capability.VIEW_STAFF_PORTAL))

    def test_inactive_user_has_no_capabilities(self):
        user = make_user(Role.OWNER, "sleepy", is_active=False)
        self.assertFalse(has_capability(user, Capability.VIEW_STAFF_PORTAL))

    def test_can_manage_user_rules(self):
        self.assertTrue(can_manage_user(self.owner, self.it_admin))
        self.assertTrue(can_manage_user(self.owner, self.cashier))
        self.assertTrue(can_manage_user(self.it_admin, self.manager))
        self.assertFalse(can_manage_user(self.it_admin, self.owner))
        self.assertFalse(can_manage_user(self.it_admin, make_user(Role.IT_ADMIN, "it2")))
        self.assertFalse(can_manage_user(self.owner, self.owner))  # never yourself
        self.assertFalse(can_manage_user(self.owner, make_user(Role.OWNER, "owner2")))
        self.assertFalse(can_manage_user(self.manager, self.cashier))
        self.assertFalse(can_manage_user(self.owner, self.customer))
