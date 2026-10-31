"""Phase 11: show/hide buttons on every password field (display only; authentication unchanged)."""
import re

from django.urls import reverse

from .helpers import PASSWORD, AccountsTestCase


class PasswordToggleTests(AccountsTestCase):
    def toggles(self, response):
        html = response.content.decode()
        inputs = re.findall(r'<input type="password"[^>]*id="([^"]+)"', html)
        buttons = re.findall(r'data-password-toggle="([^"]+)"', html)
        return inputs, buttons

    def assert_every_password_has_toggle(self, url, expected):
        inputs, buttons = self.toggles(self.client.get(url))
        self.assertEqual(len(inputs), expected, url)
        self.assertEqual(inputs, buttons, url)

    def test_public_forms(self):
        self.assert_every_password_has_toggle(reverse("accounts:customer_login"), 1)
        self.assert_every_password_has_toggle(reverse("accounts:staff_login"), 1)
        self.assert_every_password_has_toggle(reverse("accounts:register"), 2)

    def test_password_change(self):
        self.client.force_login(self.customer)
        self.assert_every_password_has_toggle(reverse("accounts:password_change"), 3)

    def test_button_is_hidden_without_javascript_and_not_a_submit(self):
        html = self.client.get(reverse("accounts:customer_login")).content.decode()
        button = re.search(r"<button[^>]*data-password-toggle[^>]*>", html).group(0)
        self.assertIn('type="button"', button)
        self.assertIn("hidden", button)
        self.assertIn('aria-label="Show password"', button)

    def test_sign_in_still_works(self):
        r = self.client.post(reverse("accounts:customer_login"), {"username": "customer@example.com", "password": PASSWORD})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.wsgi_request.user.is_authenticated)
        self.client.logout()
        r = self.client.post(reverse("accounts:customer_login"), {"username": "customer@example.com", "password": "wrong"})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.wsgi_request.user.is_authenticated)
