import re

from django.contrib.auth import SESSION_KEY
from django.core import mail
from django.test import Client
from django.urls import reverse

from apps.accounts.models import AccountAuditLog
from apps.accounts.roles import Role

from .helpers import PASSWORD, AccountsTestCase, make_user

STAFF_LOGIN = reverse("accounts:staff_login")
CUSTOMER_LOGIN = reverse("accounts:customer_login")


class PortalLoginTests(AccountsTestCase):
    def login(self, url, username, password=PASSWORD):
        return self.client.post(url, {"username": username, "password": password})

    def test_each_staff_role_lands_on_own_dashboard(self):
        expected = {
            self.owner: "dashboard:owner",
            self.it_admin: "dashboard:it_admin",
            self.manager: "dashboard:manager",
            self.cashier: "dashboard:cashier",
        }
        for user, url_name in expected.items():
            with self.subTest(role=user.role):
                self.client.logout()
                response = self.login(STAFF_LOGIN, user.username)
                self.assertRedirects(response, reverse(url_name))

    def test_staff_can_sign_in_with_email(self):
        response = self.login(STAFF_LOGIN, self.manager.email.upper())
        self.assertRedirects(response, reverse("dashboard:manager"))

    def test_customer_lands_on_customer_home(self):
        response = self.login(CUSTOMER_LOGIN, "customer@example.com")
        self.assertRedirects(response, reverse("accounts:customer_home"))

    def test_customer_cannot_use_staff_portal(self):
        response = self.login(STAFF_LOGIN, "customer@example.com")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Incorrect login details")
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_staff_cannot_use_customer_portal(self):
        response = self.login(CUSTOMER_LOGIN, self.owner.email)
        self.assertContains(response, "Incorrect login details")
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_wrong_password_shows_error(self):
        response = self.login(STAFF_LOGIN, "owner", "wrong-password")
        self.assertContains(response, "Incorrect login details")
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_inactive_account_cannot_sign_in(self):
        make_user(Role.MANAGER, "gone", is_active=False)
        response = self.login(STAFF_LOGIN, "gone")
        self.assertContains(response, "Incorrect login details")
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_deactivation_ends_existing_session(self):
        user = make_user(Role.CASHIER, "temp")
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse("dashboard:cashier")).status_code, 200)
        user.is_active = False
        user.save()
        response = self.client.get(reverse("dashboard:cashier"))
        self.assertRedirects(response, f"{STAFF_LOGIN}?next={reverse('dashboard:cashier')}")

    def test_session_rotates_on_login(self):
        self.client.get(STAFF_LOGIN)
        self.client.session.save()
        before = self.client.session.session_key
        self.login(STAFF_LOGIN, "owner")
        self.assertNotEqual(before, self.client.session.session_key)

    def test_repeated_failures_lock_the_login(self):
        for _ in range(5):
            self.login(STAFF_LOGIN, "owner", "nope")
        response = self.login(STAFF_LOGIN, "owner")  # correct password
        self.assertContains(response, "Too many failed attempts")
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_signed_in_user_visiting_login_is_redirected(self):
        self.client.force_login(self.cashier)
        self.assertRedirects(self.client.get(STAFF_LOGIN), reverse("dashboard:cashier"))


class LogoutTests(AccountsTestCase):
    def test_get_asks_for_confirmation_and_keeps_session(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse("accounts:logout"))
        self.assertContains(response, "Sign out?")
        self.assertIn(SESSION_KEY, self.client.session)

    def test_post_signs_out(self):
        self.client.force_login(self.manager)
        response = self.client.post(reverse("accounts:logout"))
        self.assertRedirects(response, STAFF_LOGIN)
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_customer_sign_out_returns_home(self):
        self.client.force_login(self.customer)
        self.assertRedirects(self.client.post(reverse("accounts:logout")), reverse("core:home"))


class CsrfTests(AccountsTestCase):
    def setUp(self):
        super().setUp()
        self.csrf_client = Client(enforce_csrf_checks=True)

    def test_login_without_token_is_rejected(self):
        response = self.csrf_client.post(STAFF_LOGIN, {"username": "owner", "password": PASSWORD})
        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "This form has expired", status_code=403)
        self.assertNotIn(SESSION_KEY, self.csrf_client.session)

    def test_logout_without_token_is_rejected(self):
        self.csrf_client.force_login(self.owner)
        response = self.csrf_client.post(reverse("accounts:logout"))
        self.assertEqual(response.status_code, 403)
        self.assertIn(SESSION_KEY, self.csrf_client.session)

    def test_staff_creation_without_token_is_rejected(self):
        self.csrf_client.force_login(self.owner)
        response = self.csrf_client.post(reverse("accounts:staff_create"), {"username": "sneaky"})
        self.assertEqual(response.status_code, 403)

    def test_login_with_token_works(self):
        page = self.csrf_client.get(STAFF_LOGIN)
        token = page.context["csrf_token"]
        response = self.csrf_client.post(STAFF_LOGIN, {"username": "owner", "password": PASSWORD, "csrfmiddlewaretoken": token})
        self.assertEqual(response.status_code, 302)


class PasswordChangeTests(AccountsTestCase):
    NEW = "Another-Strong-Pass-99"

    def test_change_password(self):
        self.client.force_login(self.cashier)
        response = self.client.post(reverse("accounts:password_change"), {
            "old_password": PASSWORD, "new_password1": self.NEW, "new_password2": self.NEW,
        })
        self.assertRedirects(response, reverse("dashboard:cashier"))
        self.cashier.refresh_from_db()
        self.assertTrue(self.cashier.check_password(self.NEW))
        self.assertIn(SESSION_KEY, self.client.session)  # stays signed in
        self.assertTrue(AccountAuditLog.objects.filter(action="password_changed", target=self.cashier).exists())

    def test_weak_new_password_rejected(self):
        self.client.force_login(self.cashier)
        response = self.client.post(reverse("accounts:password_change"), {
            "old_password": PASSWORD, "new_password1": "12345", "new_password2": "12345",
        })
        self.assertEqual(response.status_code, 200)
        self.cashier.refresh_from_db()
        self.assertTrue(self.cashier.check_password(PASSWORD))

    def test_forced_change_blocks_everything_else(self):
        user = make_user(Role.MANAGER, "fresh", must_change_password=True)
        self.client.force_login(user)
        self.assertRedirects(self.client.get(reverse("dashboard:manager")), reverse("accounts:password_change"))
        self.assertEqual(self.client.get(reverse("api:me")).status_code, 403)
        self.assertEqual(self.client.get(reverse("accounts:password_change")).status_code, 200)
        self.client.post(reverse("accounts:password_change"), {
            "old_password": PASSWORD, "new_password1": self.NEW, "new_password2": self.NEW,
        })
        user.refresh_from_db()
        self.assertFalse(user.must_change_password)
        self.assertEqual(self.client.get(reverse("dashboard:manager")).status_code, 200)


class PasswordResetTests(AccountsTestCase):
    NEW = "Reset-Strong-Pass-77"

    def test_full_reset_flow(self):
        response = self.client.post(reverse("accounts:password_reset"), {"email": "customer@example.com"})
        self.assertRedirects(response, reverse("accounts:password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertNotIn(PASSWORD, mail.outbox[0].body)
        link = re.search(r"https?://[^/]+(/password/reset/\S+/)", mail.outbox[0].body).group(1)

        response = self.client.get(link, follow=True)  # Django swaps the token for a session marker
        self.assertTrue(response.context["validlink"])
        response = self.client.post(response.redirect_chain[-1][0], {"new_password1": self.NEW, "new_password2": self.NEW})
        self.assertRedirects(response, reverse("accounts:password_reset_complete"))
        self.customer.refresh_from_db()
        self.assertTrue(self.customer.check_password(self.NEW))

    def test_unknown_email_gives_same_response_and_no_mail(self):
        response = self.client.post(reverse("accounts:password_reset"), {"email": "nobody@example.com"})
        self.assertRedirects(response, reverse("accounts:password_reset_done"))
        self.assertEqual(len(mail.outbox), 0)

    def test_inactive_account_gets_no_mail(self):
        make_user(Role.CUSTOMER, "off@example.com", email="off@example.com", is_active=False)
        self.client.post(reverse("accounts:password_reset"), {"email": "off@example.com"})
        self.assertEqual(len(mail.outbox), 0)


class NoSecretsExposedTests(AccountsTestCase):
    def test_password_hash_never_rendered(self):
        pages = {
            self.customer: ["accounts:customer_home", "accounts:customer_profile"],
            self.owner: ["dashboard:owner", "accounts:staff_list", "accounts:staff_profile"],
        }
        for user, names in pages.items():
            self.client.force_login(user)
            for name in names:
                with self.subTest(page=name):
                    content = self.client.get(reverse(name)).content.decode()
                    self.assertNotIn(user.password, content)
                    self.assertNotIn("pbkdf2_sha256$", content)
        self.client.force_login(self.owner)
        detail = self.client.get(reverse("accounts:staff_detail", args=[self.cashier.pk])).content.decode()
        self.assertNotIn(self.cashier.password, detail)
