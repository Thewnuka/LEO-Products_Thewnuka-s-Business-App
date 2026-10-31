"""
Notification pages (every signed-in user sees only their own), business alerts and alert settings.
Staff pages use the staff layout; customers see the same pages in their account area.
"""
from django import forms
from django.contrib import messages
from django.contrib.auth.mixins import AccessMixin
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import TemplateView, UpdateView

from apps.accounts.forms import BootstrapFormMixin
from apps.accounts.permissions import CUSTOMER_LOGIN_URL, CapabilityRequiredMixin
from apps.accounts.roles import Capability, Role

from . import services
from .alerts import business_alerts
from .models import AlertSettings, Category, Notification


class SignedInMixin(AccessMixin):
    login_url = CUSTOMER_LOGIN_URL

    def dispatch(self, request, *args, **kwargs):
        if not (request.user.is_authenticated and request.user.is_active):
            return self.handle_no_permission()
        return super().dispatch(request, *args, **kwargs)

    def layout(self, name):
        return f"notifications/{'staff' if self.request.user.is_staff_member else 'customer'}_{name}.html"


class NotificationListView(SignedInMixin, TemplateView):
    def get_template_names(self):
        return [self.layout("list")]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        show = self.request.GET.get("show", "all")
        category = self.request.GET.get("category", "")
        items = services.inbox(user)
        if show == "unread":
            items = items.filter(is_read=False)
        allowed = services.categories_for(user)
        if category in allowed:
            items = items.filter(category=category)
        query = self.request.GET.copy()
        query.pop("page", None)
        ctx.update(page_obj=Paginator(items, 25).get_page(self.request.GET.get("page")), show=show, category=category,
                   categories=[(c, Category(c).label) for c in allowed], querystring=query.urlencode(),
                   unread=services.unread_count(user))
        return ctx


class OpenNotificationView(SignedInMixin, View):
    """Mark as read and go to the linked page (only links inside this site)."""

    def get(self, request, pk):
        notification = get_object_or_404(Notification, pk=pk, recipient=request.user)
        services.mark_read(request.user, [notification.pk])
        return redirect(services.safe_url(notification.url) or "notifications:list")


class MarkReadView(SignedInMixin, View):
    http_method_names = ["post"]

    def post(self, request, pk=None):
        if pk is None:
            count = services.mark_read(request.user)
            messages.success(request, f"{count} notification{'s' if count != 1 else ''} marked as read.")
        elif request.POST.get("unread"):
            services.mark_unread(request.user, pk)
        else:
            services.mark_read(request.user, [pk])
        back = request.POST.get("next", "")
        return redirect(back if services.safe_url(back) else "notifications:list")


class PreferencesForm(BootstrapFormMixin, forms.Form):
    categories = forms.MultipleChoiceField(label="Show me notifications about", required=False,
                                           widget=forms.CheckboxSelectMultiple)
    email_order_updates = forms.BooleanField(label="Email me about my orders and payments", required=False)

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["categories"].choices = [(c, Category(c).label) for c in services.categories_for(user)]
        if user.role != Role.CUSTOMER:
            del self.fields["email_order_updates"]


class PreferencesView(SignedInMixin, View):
    def get_template(self):
        return self.layout("preferences")

    def get(self, request):
        pref = services.preference_for(request.user)
        available = services.categories_for(request.user)
        form = PreferencesForm(user=request.user, initial={
            "categories": [c for c in available if pref.wants(c)], "email_order_updates": pref.email_order_updates})
        return render(request, self.get_template(), {"form": form})

    def post(self, request):
        form = PreferencesForm(request.POST, user=request.user)
        if not form.is_valid():
            return render(request, self.get_template(), {"form": form})
        pref = services.preference_for(request.user)
        available = services.categories_for(request.user)
        chosen = set(form.cleaned_data["categories"])
        pref.muted_categories = sorted(c for c in available if c not in chosen)
        if "email_order_updates" in form.cleaned_data:
            pref.email_order_updates = form.cleaned_data["email_order_updates"]
        pref.save()
        messages.success(request, "Notification preferences saved.")
        return redirect("notifications:preferences")


class AlertsView(CapabilityRequiredMixin, TemplateView):
    required_capability = Capability.VIEW_STAFF_PORTAL
    template_name = "notifications/alerts.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["alerts"] = business_alerts(self.request.user)
        return ctx


class AlertSettingsForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = AlertSettings
        fields = ["pending_order_hours", "unpaid_order_days", "open_shift_hours", "reviews_need_approval"]


class AlertSettingsView(CapabilityRequiredMixin, UpdateView):
    required_capability = Capability.MANAGE_BUSINESS_SETTINGS
    form_class = AlertSettingsForm
    template_name = "notifications/alert_settings.html"

    def get_object(self, queryset=None):
        return AlertSettings.load()

    def form_valid(self, form):
        form.save()
        messages.success(self.request, "Alert settings saved.")
        return redirect("notifications:alert_settings")
