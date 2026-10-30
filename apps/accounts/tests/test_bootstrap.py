import os
from io import StringIO
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import AccountAuditLog, User
from apps.accounts.roles import Role

from .helpers import make_user

STRONG = "Owner-Bootstrap-Pass-1"
WEAK = "short1"  # fails the password rules


def run(env, *args):
    out = StringIO()
    with mock.patch.dict(os.environ, env, clear=False):
        call_command("bootstrap_owner", "--no-input", *args, stdout=out)
    return out.getvalue()


ENV = {"OWNER_USERNAME": "admin", "OWNER_EMAIL": "admin@gmail.com", "OWNER_PASSWORD": STRONG}


class BootstrapOwnerTests(TestCase):
    def test_creates_primary_owner(self):
        output = run(ENV)
        owner = User.objects.get(username="admin")
        self.assertEqual(owner.role, Role.OWNER)
        self.assertTrue(owner.is_primary_owner)
        self.assertTrue(owner.must_change_password)
        self.assertTrue(owner.is_superuser)
        self.assertTrue(owner.check_password(STRONG))
        self.assertNotIn(STRONG, owner.password)
        self.assertNotIn(STRONG, output)
        self.assertTrue(AccountAuditLog.objects.filter(action="owner_bootstrapped", target=owner).exists())

    def test_running_again_changes_nothing(self):
        run(ENV)
        output = run({**ENV, "OWNER_PASSWORD": "Completely-Different-9"})
        self.assertIn("No changes made", output)
        owner = User.objects.get(username="admin")
        self.assertTrue(owner.check_password(STRONG))
        self.assertEqual(User.objects.filter(is_primary_owner=True).count(), 1)

    def test_weak_password_rejected_by_default(self):
        with self.assertRaises(CommandError):
            run({**ENV, "OWNER_PASSWORD": WEAK})
        self.assertFalse(User.objects.exists())

    @override_settings(DEBUG=True)
    def test_weak_password_allowed_in_development_with_flag(self):
        run({**ENV, "OWNER_PASSWORD": WEAK}, "--allow-weak-password")
        owner = User.objects.get(username="admin")
        self.assertTrue(owner.check_password(WEAK))
        self.assertTrue(owner.must_change_password)

    @override_settings(DEBUG=False)
    def test_weak_password_flag_refused_in_production(self):
        with self.assertRaises(CommandError):
            run({**ENV, "OWNER_PASSWORD": WEAK}, "--allow-weak-password")
        self.assertFalse(User.objects.exists())

    def test_existing_account_is_not_touched_without_permission(self):
        existing = make_user(Role.CUSTOMER, "admin", password="Original-Pass-123")
        with self.assertRaises(CommandError):
            run(ENV)
        existing.refresh_from_db()
        self.assertEqual(existing.role, Role.CUSTOMER)
        self.assertTrue(existing.check_password("Original-Pass-123"))

    def test_promote_existing_keeps_password(self):
        existing = make_user(Role.MANAGER, "admin", password="Original-Pass-123")
        run(ENV, "--promote-existing")
        existing.refresh_from_db()
        self.assertEqual(existing.role, Role.OWNER)
        self.assertTrue(existing.is_primary_owner)
        self.assertTrue(existing.check_password("Original-Pass-123"))

    def test_missing_values_fail_without_prompting(self):
        with mock.patch.dict(os.environ, {"OWNER_USERNAME": "", "OWNER_EMAIL": "", "OWNER_PASSWORD": ""}):
            with self.assertRaises(CommandError):
                call_command("bootstrap_owner", "--no-input", stdout=StringIO())

    def test_first_sign_in_requires_password_change(self):
        run(ENV)
        response = self.client.post(reverse("accounts:staff_login"), {"username": "admin", "password": STRONG}, follow=True)
        self.assertEqual(response.redirect_chain[-1][0], reverse("accounts:password_change"))
        self.assertContains(response, "Choose a new password")
