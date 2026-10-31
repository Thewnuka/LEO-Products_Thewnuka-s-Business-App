"""
Staff dashboards, one per role.

Each describes the role's responsibilities and links only to features that
exist. Dashboards that cover the till also show today's real POS figures
(limited to what the user may see). OWNER may open every dashboard.
"""
from django.shortcuts import redirect
from django.views import View
from django.views.generic import TemplateView

from apps.accounts.permissions import RoleRequiredMixin, StaffRequiredMixin
from apps.accounts.roles import Capability, Role, has_capability
from apps.accounts.routing import home_url_for


class DashboardRedirectView(StaffRequiredMixin, View):
    def get(self, request):
        return redirect(home_url_for(request.user))


class RoleDashboardView(RoleRequiredMixin, TemplateView):
    template_name = "dashboard/role_dashboard.html"
    dashboard_role = None
    title = ""
    summary = ""
    responsibilities = ()
    upcoming = ()  # (module, phase)
    shows_pos = False

    def get_context_data(self, **kwargs):
        user = self.request.user
        if self.shows_pos and (has_capability(user, Capability.VIEW_POS_SALES)
                               or has_capability(user, Capability.PROCESS_SALES)):
            from apps.pos.services import current_shift, today_summary

            kwargs["pos_today"] = today_summary(user)
            kwargs["my_shift"] = current_shift(user) if has_capability(user, Capability.PROCESS_SALES) else None
        return super().get_context_data(
            dashboard_role=self.dashboard_role,
            dashboard_title=self.title,
            summary=self.summary,
            responsibilities=self.responsibilities,
            upcoming=self.upcoming,
            viewing_other_role=self.request.user.role != self.dashboard_role,
            **kwargs,
        )


class OwnerDashboardView(RoleDashboardView):
    allowed_roles = (Role.OWNER,)
    dashboard_role = Role.OWNER
    title = "Owner dashboard"
    summary = "Full oversight of LEO PRODUCTS: people, settings, operations and finances."
    responsibilities = (
        "Create and manage staff accounts and their roles",
        "Manage business settings and user permissions",
        "Oversee products, inventory, orders, payments and finance",
        "View every dashboard and report",
    )
    shows_pos = True
    upcoming = (
        ("Business settings & logo upload", "08"),
    )


class ITAdminDashboardView(RoleDashboardView):
    allowed_roles = (Role.OWNER, Role.IT_ADMIN)
    dashboard_role = Role.IT_ADMIN
    title = "IT Admin dashboard"
    summary = "Technical configuration, system users and security."
    responsibilities = (
        "Manage Manager and Cashier accounts",
        "Maintain technical settings and system health",
        "Review security-related account activity",
        "No access to financial operations or business settings",
    )
    upcoming = (
        ("Technical settings", "08"),
        ("System maintenance tools", "08"),
        ("Security activity log viewer", "08"),
    )


class ManagerDashboardView(RoleDashboardView):
    allowed_roles = (Role.OWNER, Role.MANAGER)
    dashboard_role = Role.MANAGER
    title = "Manager dashboard"
    summary = "Day-to-day business operations."
    responsibilities = (
        "Manage products and categories",
        "Manage inventory and suppliers",
        "Manage customer orders and customers",
        "View operational reports",
    )
    shows_pos = True


class CashierDashboardView(RoleDashboardView):
    allowed_roles = (Role.OWNER, Role.CASHIER)
    dashboard_role = Role.CASHIER
    title = "Cashier dashboard"
    summary = "In-store sales at the point of sale."
    responsibilities = (
        "Process sales at the POS",
        "Issue receipts",
        "Take permitted payments",
        "View your own transactions",
    )
    shows_pos = True
