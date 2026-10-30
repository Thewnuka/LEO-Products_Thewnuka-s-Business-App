from django.urls import reverse

from apps.accounts.tests.helpers import AccountsTestCase


class RoleDashboardTests(AccountsTestCase):
    def test_placeholder_content_and_no_fake_figures(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("dashboard:owner"))
        self.assertTemplateUsed(response, "dashboard/role_dashboard.html")
        self.assertContains(response, "Owner dashboard")
        self.assertContains(response, "Coming in later phases")
        for fake in ("Total sales", "Revenue", "Rs."):
            self.assertNotContains(response, fake)

    def test_staff_links_follow_role(self):
        self.client.force_login(self.owner)
        self.assertContains(self.client.get(reverse("dashboard:owner")), reverse("accounts:staff_list"))
        self.client.force_login(self.cashier)
        self.assertNotContains(self.client.get(reverse("dashboard:cashier")), reverse("accounts:staff_list"))

    def test_owner_sees_notice_on_other_role_dashboards(self):
        self.client.force_login(self.owner)
        self.assertContains(self.client.get(reverse("dashboard:cashier")), "viewing another role")
