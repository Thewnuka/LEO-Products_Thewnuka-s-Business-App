from django.contrib import messages
from django.contrib.auth import login, logout, views as auth_views
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Case, IntegerField, Q, Value, When
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.debug import sensitive_post_parameters
from django.views.generic import CreateView, DetailView, FormView, TemplateView, UpdateView

from . import audit
from .forms import (
    CustomerLoginForm,
    CustomerRegistrationForm,
    LeoPasswordChangeForm,
    LeoPasswordResetForm,
    LeoSetPasswordForm,
    ProfileForm,
    StaffCreateForm,
    StaffFilterForm,
    StaffLoginForm,
    StaffUpdateForm,
    TemporaryPasswordForm,
)
from .models import AccountAuditLog, User
from .permissions import CapabilityRequiredMixin, CustomerRequiredMixin, StaffRequiredMixin
from .roles import STAFF_ROLES, Capability, Role, assignable_roles, can_manage_user
from .routing import home_url_for

Action = AccountAuditLog.Action


# ---------------------------------------------------------------------------
# Sign in / sign out
# ---------------------------------------------------------------------------
class PortalLoginView(auth_views.LoginView):
    redirect_authenticated_user = True

    def get_default_redirect_url(self):
        return home_url_for(self.request.user)


class StaffLoginView(PortalLoginView):
    form_class = StaffLoginForm
    template_name = "accounts/staff_login.html"


class CustomerLoginView(PortalLoginView):
    form_class = CustomerLoginForm
    template_name = "accounts/customer_login.html"


class LoginRedirectView(View):
    """Send a signed-in user to the home page for their role."""

    def get(self, request):
        return redirect(home_url_for(request.user))


class LogoutView(auth_views.LogoutView):
    """GET shows a confirmation page; POST (with CSRF token) signs out."""

    http_method_names = ["get", "post", "options"]
    template_name = "accounts/logout_confirm.html"

    def get(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("core:home")
        return self.render_to_response(self.get_context_data())

    def post(self, request, *args, **kwargs):
        was_staff = request.user.is_authenticated and request.user.is_staff_member
        logout(request)
        messages.success(request, "You have been signed out.")
        return redirect("accounts:staff_login" if was_staff else "core:home")


# ---------------------------------------------------------------------------
# Customer registration
# ---------------------------------------------------------------------------
@method_decorator(sensitive_post_parameters("password1", "password2"), name="dispatch")
class CustomerRegisterView(CreateView):
    form_class = CustomerRegistrationForm
    template_name = "accounts/register.html"

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect(home_url_for(request.user))
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        user = form.save()
        audit.record(Action.CUSTOMER_REGISTERED, actor=None, target=user, request=self.request)
        login(self.request, user, backend="apps.accounts.backends.EmailOrUsernameModelBackend")
        messages.success(self.request, f"Welcome, {user.first_name}! Your account has been created.")
        return redirect("accounts:customer_home")


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------
class PasswordChangeView(auth_views.PasswordChangeView):
    form_class = LeoPasswordChangeForm
    template_name = "accounts/password_change.html"

    def form_valid(self, form):
        form.user.must_change_password = False  # saved by form.save() in super()
        response = super().form_valid(form)
        audit.record(Action.PASSWORD_CHANGED, actor=self.request.user, target=self.request.user, request=self.request)
        messages.success(self.request, "Your password has been changed.")
        return response

    def get_success_url(self):
        return home_url_for(self.request.user)


class PasswordResetView(auth_views.PasswordResetView):
    """Same response whether or not the email exists, so accounts cannot be discovered."""

    form_class = LeoPasswordResetForm
    template_name = "accounts/password_reset_form.html"
    extra_email_context = {"site_name": "LEO PRODUCTS"}
    email_template_name = "accounts/email/password_reset_email.txt"
    subject_template_name = "accounts/email/password_reset_subject.txt"
    success_url = reverse_lazy("accounts:password_reset_done")


class PasswordResetDoneView(auth_views.PasswordResetDoneView):
    template_name = "accounts/password_reset_done.html"


class PasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    form_class = LeoSetPasswordForm
    template_name = "accounts/password_reset_confirm.html"
    success_url = reverse_lazy("accounts:password_reset_complete")

    def form_valid(self, form):
        form.user.must_change_password = False
        response = super().form_valid(form)
        audit.record(Action.PASSWORD_RESET, target=form.user, request=self.request)
        return response


class PasswordResetCompleteView(auth_views.PasswordResetCompleteView):
    template_name = "accounts/password_reset_complete.html"


# ---------------------------------------------------------------------------
# Customer portal (customers only; every view works on request.user)
# ---------------------------------------------------------------------------
class CustomerHomeView(CustomerRequiredMixin, TemplateView):
    template_name = "accounts/customer/home.html"

    def get_context_data(self, **kwargs):
        from apps.orders.models import Order
        from apps.payments.models import Payment

        user = self.request.user
        return super().get_context_data(
            recent_orders=Order.objects.filter(customer=user).order_by("-created_at", "-pk")[:3],
            recent_payments=(Payment.objects.filter(order__customer=user).select_related("order")
                             .order_by("-created_at", "-pk")[:3]),
            **kwargs,
        )


class CustomerProfileView(CustomerRequiredMixin, UpdateView):
    form_class = ProfileForm
    template_name = "accounts/customer/profile.html"
    success_url = reverse_lazy("accounts:customer_profile")

    def get_object(self, queryset=None):
        return self.request.user

    def form_valid(self, form):
        response = super().form_valid(form)
        if form.changed_data:
            audit.record(Action.PROFILE_UPDATED, actor=self.request.user, target=self.request.user,
                         request=self.request, fields=sorted(form.changed_data))
        messages.success(self.request, "Your profile has been updated.")
        return response


# ---------------------------------------------------------------------------
# Staff self-service
# ---------------------------------------------------------------------------
class StaffProfileView(StaffRequiredMixin, UpdateView):
    form_class = ProfileForm
    template_name = "accounts/staff/profile.html"
    success_url = reverse_lazy("accounts:staff_profile")

    def get_object(self, queryset=None):
        return self.request.user

    def form_valid(self, form):
        response = super().form_valid(form)
        if form.changed_data:
            audit.record(Action.PROFILE_UPDATED, actor=self.request.user, target=self.request.user,
                         request=self.request, fields=sorted(form.changed_data))
        messages.success(self.request, "Your details have been updated.")
        return response


# ---------------------------------------------------------------------------
# Staff account management (OWNER; IT_ADMIN for Manager/Cashier accounts)
# ---------------------------------------------------------------------------
ROLE_ORDER = (Role.OWNER, Role.IT_ADMIN, Role.MANAGER, Role.CASHIER)


def staff_queryset():
    return User.objects.filter(role__in=STAFF_ROLES)


class StaffListView(CapabilityRequiredMixin, TemplateView):
    required_capability = Capability.VIEW_STAFF
    template_name = "accounts/staff/user_list.html"
    paginate_by = 20

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        form = StaffFilterForm(self.request.GET or None)
        seniority = Case(*[When(role=r, then=Value(i)) for i, r in enumerate(ROLE_ORDER)], output_field=IntegerField())
        users = staff_queryset().order_by(seniority, "first_name", "username")
        if form.is_valid():
            q = form.cleaned_data["q"].strip()
            if q:
                users = users.filter(
                    Q(username__icontains=q) | Q(first_name__icontains=q)
                    | Q(last_name__icontains=q) | Q(email__icontains=q)
                )
            if form.cleaned_data["role"]:
                users = users.filter(role=form.cleaned_data["role"])
            if form.cleaned_data["status"]:
                users = users.filter(is_active=form.cleaned_data["status"] == "active")
        page = Paginator(users, self.paginate_by).get_page(self.request.GET.get("page"))
        query = self.request.GET.copy()
        query.pop("page", None)
        ctx.update(
            filter_form=form,
            page_obj=page,
            querystring=query.urlencode(),
            can_create=bool(assignable_roles(self.request.user)),
        )
        return ctx


class ManagedStaffMixin(CapabilityRequiredMixin):
    """Loads the target staff account and checks the actor may manage it."""

    required_capability = Capability.MANAGE_STAFF

    def get_target(self):
        target = get_object_or_404(staff_queryset(), pk=self.kwargs["pk"])
        if not can_manage_user(self.request.user, target):
            raise PermissionDenied
        return target


@method_decorator(sensitive_post_parameters("password1", "password2"), name="dispatch")
class StaffCreateView(CapabilityRequiredMixin, CreateView):
    required_capability = Capability.MANAGE_STAFF
    form_class = StaffCreateForm
    template_name = "accounts/staff/user_form.html"

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "actor": self.request.user}

    def form_valid(self, form):
        with transaction.atomic():
            user = form.save()
            audit.record(Action.STAFF_CREATED, actor=self.request.user, target=user,
                         request=self.request, role=user.role)
        messages.success(self.request, f"Staff account “{user.username}” created. They must change the temporary password at first sign-in.")
        return redirect("accounts:staff_detail", pk=user.pk)


class StaffDetailView(CapabilityRequiredMixin, DetailView):
    required_capability = Capability.VIEW_STAFF
    template_name = "accounts/staff/user_detail.html"
    context_object_name = "member"

    def get_queryset(self):
        return staff_queryset()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["can_manage"] = can_manage_user(self.request.user, self.object)
        ctx["audit_events"] = (
            AccountAuditLog.objects.filter(target=self.object).select_related("actor")[:15]
        )
        return ctx


class StaffUpdateView(ManagedStaffMixin, UpdateView):
    form_class = StaffUpdateForm
    template_name = "accounts/staff/user_form.html"
    context_object_name = "member"

    def get_object(self, queryset=None):
        return self.get_target()

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "actor": self.request.user}

    def form_valid(self, form):
        old_role = User.objects.only("role").get(pk=self.object.pk).role
        with transaction.atomic():
            user = form.save()
            changed = [f for f in form.changed_data if f != "role"]
            if changed:
                audit.record(Action.STAFF_UPDATED, actor=self.request.user, target=user,
                             request=self.request, fields=sorted(changed))
            if user.role != old_role:
                audit.record(Action.ROLE_CHANGED, actor=self.request.user, target=user,
                             request=self.request, old_role=old_role, new_role=user.role)
        messages.success(self.request, "Staff details saved.")
        return redirect("accounts:staff_detail", pk=user.pk)


class StaffToggleActiveView(ManagedStaffMixin, View):
    http_method_names = ["post"]

    def post(self, request, pk):
        target = self.get_target()
        target.is_active = not target.is_active
        with transaction.atomic():
            target.save(update_fields=["is_active"])
            audit.record(Action.ACTIVATED if target.is_active else Action.DEACTIVATED,
                         actor=request.user, target=target, request=request)
        if target.is_active:
            messages.success(request, f"{target} can sign in again.")
        else:
            messages.success(request, f"{target} has been deactivated and signed out everywhere.")
        return redirect("accounts:staff_detail", pk=target.pk)


@method_decorator(sensitive_post_parameters("password1", "password2"), name="dispatch")
class StaffSetPasswordView(ManagedStaffMixin, FormView):
    form_class = TemporaryPasswordForm
    template_name = "accounts/staff/user_set_password.html"

    def get(self, request, *args, **kwargs):
        self.target = self.get_target()
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        self.target = self.get_target()
        return super().post(request, *args, **kwargs)

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "user": self.target}

    def get_context_data(self, **kwargs):
        return super().get_context_data(member=self.target, **kwargs)

    def form_valid(self, form):
        with transaction.atomic():
            form.save()
            audit.record(Action.PASSWORD_SET_BY_ADMIN, actor=self.request.user, target=self.target, request=self.request)
        messages.success(self.request, f"Temporary password set. {self.target} must change it at next sign-in; their other sessions have been signed out.")
        return redirect(reverse("accounts:staff_detail", kwargs={"pk": self.target.pk}))
