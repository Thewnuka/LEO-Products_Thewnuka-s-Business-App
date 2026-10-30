"""
Backend enforcement of roles and capabilities.

Pages (class-based views):
    class StaffListView(CapabilityRequiredMixin, ListView):
        required_capability = Capability.VIEW_STAFF

Pages (function views):
    @capability_required(Capability.USE_POS)
    def pos_screen(request): ...

API (Django REST Framework):
    class ProductViewSet(ModelViewSet):
        permission_classes = [HasCapability]
        required_capability = Capability.MANAGE_CATALOG

Signed-out visitors are sent to the right login page; signed-in users
without permission get the branded 403 page. Hiding links in templates is
only a convenience; these checks are what actually protect each URL.
"""
from functools import wraps

from django.contrib.auth.mixins import AccessMixin
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import ImproperlyConfigured, PermissionDenied
from django.urls import reverse_lazy
from rest_framework.permissions import BasePermission

from .roles import Capability, has_capability

STAFF_LOGIN_URL = reverse_lazy("accounts:staff_login")
CUSTOMER_LOGIN_URL = reverse_lazy("accounts:customer_login")


class CapabilityRequiredMixin(AccessMixin):
    """Allow the view only to active users whose role has `required_capability`."""

    required_capability = None
    login_url = STAFF_LOGIN_URL

    def dispatch(self, request, *args, **kwargs):
        if self.required_capability is None:
            raise ImproperlyConfigured(f"{type(self).__name__} must set required_capability.")
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not has_capability(request.user, self.required_capability):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


class StaffRequiredMixin(CapabilityRequiredMixin):
    required_capability = Capability.VIEW_STAFF_PORTAL


class CustomerRequiredMixin(CapabilityRequiredMixin):
    required_capability = Capability.USE_CUSTOMER_PORTAL
    login_url = CUSTOMER_LOGIN_URL


class RoleRequiredMixin(AccessMixin):
    """Allow the view only to users whose role is in `allowed_roles`."""

    allowed_roles = ()
    login_url = STAFF_LOGIN_URL

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not request.user.is_active or request.user.role not in self.allowed_roles:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


def capability_required(capability, login_url=STAFF_LOGIN_URL):
    """Decorator version of CapabilityRequiredMixin for function-based views."""

    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path(), str(login_url))
            if not has_capability(request.user, capability):
                raise PermissionDenied
            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator


class HasCapability(BasePermission):
    """DRF permission: the view's `required_capability` must be granted."""

    def has_permission(self, request, view):
        capability = getattr(view, "required_capability", None)
        if capability is None:
            raise ImproperlyConfigured(f"{type(view).__name__} must set required_capability.")
        return has_capability(request.user, capability)
