from django.urls import reverse

from apps.accounts.models import AccountAuditLog, User
from apps.accounts.roles import Role

from .helpers import PASSWORD, AccountsTestCase, make_user

TEMP = "Temporary-Pass-4321"


def staff_data(**overrides):
    data = {
        "username": "newcashier",
        "first_name": "Sunil",
        "last_name": "Fernando",
        "email": "sunil@example.com",
        "phone_number": "0712345678",
        "role": Role.CASHIER,
        "password1": TEMP,
        "password2": TEMP,
    }
    data.update(overrides)
    return data


class StaffCreateTests(AccountsTestCase):
    def test_owner_creates_staff_with_temporary_password(self):
        self.client.force_login(self.owner)
        response = self.client.post(reverse("accounts:staff_create"), staff_data())
        user = User.objects.get(username="newcashier")
        self.assertRedirects(response, reverse("accounts:staff_detail", args=[user.pk]))
        self.assertEqual(user.role, Role.CASHIER)
        self.assertTrue(user.must_change_password)
        self.assertTrue(user.check_password(TEMP))
        self.assertNotIn(TEMP, user.password)
        log = AccountAuditLog.objects.get(action="staff_created", target=user)
        self.assertEqual(log.actor, self.owner)
        self.assertNotIn(TEMP, str(log.details))

    def test_owner_cannot_create_owner_accounts(self):
        self.client.force_login(self.owner)
        response = self.client.post(reverse("accounts:staff_create"), staff_data(role=Role.OWNER))
        self.assertEqual(response.status_code, 200)
        self.assertIn("role", response.context["form"].errors)
        self.assertFalse(User.objects.filter(username="newcashier").exists())

    def test_it_admin_can_create_manager_but_not_it_admin(self):
        self.client.force_login(self.it_admin)
        self.client.post(reverse("accounts:staff_create"), staff_data(role=Role.MANAGER))
        self.assertEqual(User.objects.get(username="newcashier").role, Role.MANAGER)
        response = self.client.post(reverse("accounts:staff_create"), staff_data(username="x2", email="x2@example.com", role=Role.IT_ADMIN))
        self.assertIn("role", response.context["form"].errors)
        self.assertFalse(User.objects.filter(username="x2").exists())

    def test_customer_and_cashier_cannot_create_staff(self):
        for user in (self.customer, self.cashier, self.manager):
            self.client.force_login(user)
            response = self.client.post(reverse("accounts:staff_create"), staff_data(role=Role.OWNER))
            self.assertEqual(response.status_code, 403)
        self.assertFalse(User.objects.filter(username="newcashier").exists())

    def test_duplicate_email_rejected(self):
        self.client.force_login(self.owner)
        response = self.client.post(reverse("accounts:staff_create"), staff_data(email=self.manager.email.upper()))
        self.assertIn("email", response.context["form"].errors)


class StaffEditTests(AccountsTestCase):
    def edit(self, actor, target, **overrides):
        self.client.force_login(actor)
        data = {"first_name": target.first_name or "N", "last_name": "L", "email": target.email,
                "phone_number": "", "role": target.role}
        data.update(overrides)
        return self.client.post(reverse("accounts:staff_update", args=[target.pk]), data)

    def test_owner_changes_role_and_it_is_audited(self):
        response = self.edit(self.owner, self.manager, role=Role.CASHIER)
        self.assertRedirects(response, reverse("accounts:staff_detail", args=[self.manager.pk]))
        self.manager.refresh_from_db()
        self.assertEqual(self.manager.role, Role.CASHIER)
        log = AccountAuditLog.objects.get(action="role_changed", target=self.manager)
        self.assertEqual(log.details, {"old_role": "MANAGER", "new_role": "CASHIER"})

    def test_cannot_promote_to_owner(self):
        response = self.edit(self.owner, self.manager, role=Role.OWNER)
        self.assertIn("role", response.context["form"].errors)
        self.manager.refresh_from_db()
        self.assertEqual(self.manager.role, Role.MANAGER)

    def test_it_admin_cannot_promote_to_it_admin(self):
        response = self.edit(self.it_admin, self.manager, role=Role.IT_ADMIN)
        self.assertIn("role", response.context["form"].errors)

    def test_nobody_can_edit_themselves_through_staff_management(self):
        for user in (self.owner, self.it_admin):
            response = self.edit(user, user, role=Role.OWNER)
            self.assertEqual(response.status_code, 403)
        self.it_admin.refresh_from_db()
        self.assertEqual(self.it_admin.role, Role.IT_ADMIN)

    def test_it_admin_cannot_manage_owner_or_other_it_admins(self):
        other_it = make_user(Role.IT_ADMIN, "it2")
        for target in (self.owner, other_it):
            self.assertEqual(self.edit(self.it_admin, target, role=Role.CASHIER).status_code, 403)
            self.client.force_login(self.it_admin)
            self.assertEqual(self.client.post(reverse("accounts:staff_toggle_active", args=[target.pk])).status_code, 403)

    def test_customer_accounts_not_reachable_through_staff_urls(self):
        self.client.force_login(self.owner)
        for name in ("staff_detail", "staff_update", "staff_set_password"):
            self.assertEqual(self.client.get(reverse(f"accounts:{name}", args=[self.customer.pk])).status_code, 404)

    def test_staff_profile_cannot_change_role(self):
        self.client.force_login(self.cashier)
        self.client.post(reverse("accounts:staff_profile"), {
            "first_name": "C", "last_name": "D", "email": self.cashier.email, "phone_number": "",
            "role": Role.OWNER, "is_superuser": "on",
        })
        self.cashier.refresh_from_db()
        self.assertEqual(self.cashier.role, Role.CASHIER)
        self.assertFalse(self.cashier.is_superuser)


class PrimaryOwnerManagementTests(AccountsTestCase):
    def setUp(self):
        super().setUp()
        self.primary = make_user(Role.OWNER, "admin")
        self.primary.is_primary_owner = True
        self.primary.save()

    def test_no_one_can_change_the_primary_owner_through_the_ui(self):
        for actor in (self.owner, self.it_admin):
            self.client.force_login(actor)
            for name in ("staff_update", "staff_set_password"):
                self.assertEqual(self.client.get(reverse(f"accounts:{name}", args=[self.primary.pk])).status_code, 403)
            self.assertEqual(self.client.post(reverse("accounts:staff_toggle_active", args=[self.primary.pk])).status_code, 403)
        self.primary.refresh_from_db()
        self.assertTrue(self.primary.is_active)
        self.assertEqual(self.primary.role, Role.OWNER)

    def test_django_admin_cannot_delete_primary_owner(self):
        self.client.force_login(self.owner)
        url = reverse("admin:accounts_user_delete", args=[self.primary.pk])
        self.assertEqual(self.client.post(url, {"post": "yes"}).status_code, 403)
        self.assertTrue(User.objects.filter(pk=self.primary.pk).exists())


class ActivationAndPasswordTests(AccountsTestCase):
    def test_deactivate_then_reactivate(self):
        self.client.force_login(self.owner)
        url = reverse("accounts:staff_toggle_active", args=[self.cashier.pk])
        self.assertEqual(self.client.get(url).status_code, 405)  # POST only
        self.client.post(url)
        self.cashier.refresh_from_db()
        self.assertFalse(self.cashier.is_active)
        self.assertTrue(AccountAuditLog.objects.filter(action="deactivated", target=self.cashier).exists())

        other = self.client_class()
        response = other.post(reverse("accounts:staff_login"), {"username": "cashier", "password": PASSWORD})
        self.assertContains(response, "Incorrect login details")

        self.client.post(url)
        self.cashier.refresh_from_db()
        self.assertTrue(self.cashier.is_active)

    def test_set_temporary_password_signs_out_other_sessions(self):
        cashier_client = self.client_class()
        cashier_client.force_login(self.cashier)
        self.assertEqual(cashier_client.get(reverse("dashboard:cashier")).status_code, 200)

        self.client.force_login(self.owner)
        response = self.client.post(reverse("accounts:staff_set_password", args=[self.cashier.pk]),
                                    {"password1": TEMP, "password2": TEMP})
        self.assertRedirects(response, reverse("accounts:staff_detail", args=[self.cashier.pk]))
        self.cashier.refresh_from_db()
        self.assertTrue(self.cashier.check_password(TEMP))
        self.assertTrue(self.cashier.must_change_password)
        self.assertEqual(cashier_client.get(reverse("dashboard:cashier")).status_code, 302)
        self.assertTrue(AccountAuditLog.objects.filter(action="password_set_by_admin", target=self.cashier).exists())

    def test_manager_cannot_reset_cashier_password(self):
        self.client.force_login(self.manager)
        response = self.client.post(reverse("accounts:staff_set_password", args=[self.cashier.pk]),
                                    {"password1": TEMP, "password2": TEMP})
        self.assertEqual(response.status_code, 403)
        self.cashier.refresh_from_db()
        self.assertTrue(self.cashier.check_password(PASSWORD))


class StaffListTests(AccountsTestCase):
    def test_lists_staff_only_and_filters(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("accounts:staff_list"))
        names = {u.username for u in response.context["page_obj"]}
        self.assertEqual(names, {"owner", "itadmin", "manager", "cashier"})
        response = self.client.get(reverse("accounts:staff_list"), {"role": Role.CASHIER})
        self.assertEqual([u.username for u in response.context["page_obj"]], ["cashier"])
        response = self.client.get(reverse("accounts:staff_list"), {"q": "manag"})
        self.assertEqual([u.username for u in response.context["page_obj"]], ["manager"])
