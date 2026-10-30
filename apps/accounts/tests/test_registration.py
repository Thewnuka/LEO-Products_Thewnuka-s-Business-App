from django.contrib.auth import SESSION_KEY
from django.urls import reverse

from apps.accounts.models import AccountAuditLog, User
from apps.accounts.roles import Role

from .helpers import AccountsTestCase

REGISTER = reverse("accounts:register")
STRONG = "Fresh-Customer-Pass-1"


def form_data(**overrides):
    data = {
        "first_name": "Nimal",
        "last_name": "Perera",
        "email": "Nimal@Example.com",
        "phone_number": "+94 77 123 4567",
        "password1": STRONG,
        "password2": STRONG,
    }
    data.update(overrides)
    return data


class CustomerRegistrationTests(AccountsTestCase):
    def test_registration_creates_signed_in_customer(self):
        response = self.client.post(REGISTER, form_data())
        self.assertRedirects(response, reverse("accounts:customer_home"))
        user = User.objects.get(email="nimal@example.com")
        self.assertEqual(user.role, Role.CUSTOMER)
        self.assertEqual(user.username, "nimal@example.com")
        self.assertFalse(user.is_staff or user.is_superuser)
        self.assertTrue(user.check_password(STRONG))
        self.assertNotIn(STRONG, user.password)
        self.assertEqual(int(self.client.session[SESSION_KEY]), user.pk)
        self.assertTrue(AccountAuditLog.objects.filter(action="customer_registered", target=user).exists())

    def test_role_and_flags_in_request_are_ignored(self):
        self.client.post(REGISTER, form_data(
            role=Role.OWNER, is_staff="on", is_superuser="on", is_primary_owner="on",
            must_change_password="on", is_active="off",
        ))
        user = User.objects.get(email="nimal@example.com")
        self.assertEqual(user.role, Role.CUSTOMER)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.is_primary_owner)
        self.assertTrue(user.is_active)

    def test_duplicate_email_rejected_case_insensitively(self):
        response = self.client.post(REGISTER, form_data(email="CUSTOMER@example.com"))
        self.assertContains(response, "already exists")
        self.assertEqual(User.objects.filter(email__iexact="customer@example.com").count(), 1)

    def test_validation_errors(self):
        cases = {
            "mismatch": form_data(password2="Different-Pass-22"),
            "too short": form_data(password1="12345", password2="12345"),
            "bad email": form_data(email="not-an-email"),
            "bad phone": form_data(phone_number="call me"),
            "missing name": form_data(first_name=""),
            "missing phone": form_data(phone_number=""),
        }
        for label, data in cases.items():
            with self.subTest(label):
                response = self.client.post(REGISTER, data)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["form"].errors)
        self.assertFalse(User.objects.filter(email="nimal@example.com").exists())

    def test_signed_in_users_are_redirected_away(self):
        self.client.force_login(self.customer)
        self.assertRedirects(self.client.get(REGISTER), reverse("accounts:customer_home"))


class CustomerProfileTests(AccountsTestCase):
    def test_customer_can_update_own_profile_but_not_role(self):
        self.client.force_login(self.customer)
        response = self.client.post(reverse("accounts:customer_profile"), {
            "first_name": "Kamala", "last_name": "Silva", "email": "customer@example.com",
            "phone_number": "0771234567", "role": Role.OWNER, "is_staff": "on",
        })
        self.assertRedirects(response, reverse("accounts:customer_profile"))
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.first_name, "Kamala")
        self.assertEqual(self.customer.role, Role.CUSTOMER)
        self.assertFalse(self.customer.is_staff)

    def test_cannot_take_another_users_email(self):
        self.client.force_login(self.customer)
        response = self.client.post(reverse("accounts:customer_profile"), {
            "first_name": "A", "last_name": "B", "email": self.manager.email, "phone_number": "",
        })
        self.assertContains(response, "Another account already uses this email")

    def test_profile_only_shows_own_data(self):
        other = User.objects.create_user("other@example.com", "other@example.com", "x-Strong-Pass-1",
                                         first_name="Secret", last_name="Person", phone_number="0700000000")
        self.client.force_login(self.customer)
        for name in ("accounts:customer_home", "accounts:customer_profile"):
            content = self.client.get(reverse(name)).content.decode()
            self.assertNotIn(other.email, content)
            self.assertNotIn("0700000000", content)


class CustomerPasswordPolicyTests(AccountsTestCase):
    """Customers need only 6+ characters; staff keep the strict rules."""

    def register(self, password, confirm=None, email="simple@example.com"):
        return self.client.post(REGISTER, form_data(email=email, password1=password,
                                                    password2=password if confirm is None else confirm))

    def test_simple_passwords_are_accepted_and_hashed(self):
        for i, password in enumerate(["123456", "leo123", "mypassword", "abcdef"]):
            with self.subTest(password=password):
                self.client.logout()
                email = f"simple{i}@example.com"
                response = self.register(password, email=email)
                self.assertRedirects(response, reverse("accounts:customer_home"))
                user = User.objects.get(email=email)
                self.assertTrue(user.check_password(password))
                self.assertTrue(user.password.startswith("pbkdf2_sha256$"))
                self.assertNotIn(password, user.password)

    def test_short_password_rejected(self):
        for password in ("12345", "abc", "a"):
            with self.subTest(password=password):
                response = self.register(password)
                self.assertIn("password1", response.context["form"].errors)
        self.assertFalse(User.objects.filter(email="simple@example.com").exists())

    def test_mismatched_confirmation_rejected(self):
        response = self.register("123456", confirm="1234567")
        self.assertIn("password2", response.context["form"].errors)
        self.assertFalse(User.objects.filter(email="simple@example.com").exists())

    def test_help_text_and_browser_rule(self):
        response = self.client.get(REGISTER)
        self.assertContains(response, "Password must contain at least 6 characters.")
        self.assertContains(response, 'minlength="6"', count=2)
        for strict_message in ("too similar", "commonly used", "entirely numeric", "at least 10"):
            self.assertNotContains(response, strict_message)
        self.assertContains(response, "csrfmiddlewaretoken")

    def test_customer_can_sign_in_with_simple_password(self):
        self.register("leo123")
        self.client.logout()
        response = self.client.post(reverse("accounts:customer_login"), {"username": "simple@example.com", "password": "leo123"})
        self.assertRedirects(response, reverse("accounts:customer_home"))

    def test_staff_passwords_stay_strict(self):
        self.client.force_login(self.owner)
        response = self.client.post(reverse("accounts:staff_create"), {
            "username": "newcashier", "first_name": "A", "last_name": "B", "email": "nc@example.com",
            "phone_number": "", "role": Role.CASHIER, "password1": "123456", "password2": "123456"})
        self.assertIn("password1", response.context["form"].errors)
        self.assertFalse(User.objects.filter(username="newcashier").exists())
        response = self.client.get(reverse("accounts:staff_create"))
        self.assertContains(response, 'minlength="10"')
        self.client.force_login(self.cashier)
        response = self.client.post(reverse("accounts:password_change"),
                                    {"old_password": "Leo-Test-Pass-2026!", "new_password1": "123456", "new_password2": "123456"})
        self.assertIn("new_password2", response.context["form"].errors)  # Django reports it on the confirmation field
