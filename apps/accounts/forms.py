"""
Account forms.

Security rule: every form lists its fields explicitly. `role`, `is_active`,
`is_staff`, `is_superuser` and `is_primary_owner` are never form fields that
a user can submit for themselves; roles are set in code or chosen from the
limited list the signed-in manager is allowed to assign.
"""
from django import forms
from django.conf import settings
from django.contrib.auth import password_validation
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm, PasswordResetForm, SetPasswordForm

from . import throttling
from .models import User, identifier_taken
from .roles import STAFF_ROLES, Role, assignable_roles


class BootstrapFormMixin:
    """Adds Bootstrap classes and error states to every widget."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, (forms.CheckboxInput, forms.RadioSelect)):
                css = "form-check-input"
            elif isinstance(widget, forms.Select):
                css = "form-select"
            else:
                css = "form-control"
            widget.attrs["class"] = f"{widget.attrs.get('class', '')} {css}".strip()

    def full_clean(self):
        super().full_clean()
        for name in self.errors:
            if name in self.fields:
                widget = self.fields[name].widget
                widget.attrs["class"] = f"{widget.attrs.get('class', '')} is-invalid".strip()
                widget.attrs["aria-invalid"] = "true"


def _email_taken(email, exclude_pk=None):
    return identifier_taken(email, exclude_pk=exclude_pk)


class PasswordPairMixin:
    """
    password1 / password2 fields validated with Django's password validators.

    By default the strict AUTH_PASSWORD_VALIDATORS apply. A form can name a
    different validator list in `password_validators_setting` (customer
    registration uses the simpler CUSTOMER_PASSWORD_VALIDATORS).
    """

    password_label = "Password"
    password_validators_setting = None  # None = settings.AUTH_PASSWORD_VALIDATORS
    password_help_text = None           # None = Django's generated rule list

    def _password_validators(self):
        if self.password_validators_setting is None:
            return None  # Django then uses AUTH_PASSWORD_VALIDATORS
        return password_validation.get_password_validators(getattr(settings, self.password_validators_setting))

    def _add_password_fields(self):
        validators = self._password_validators()
        attrs = {"autocomplete": "new-password", "class": "form-control"}
        # Mirror the minimum length in the browser so both sides use the same rule.
        for validator in validators or password_validation.get_default_password_validators():
            if isinstance(validator, password_validation.MinimumLengthValidator):
                attrs["minlength"] = validator.min_length
        self.fields["password1"] = forms.CharField(
            label=self.password_label,
            strip=False,
            widget=forms.PasswordInput(attrs=attrs),
            help_text=self.password_help_text or password_validation.password_validators_help_text_html(validators),
        )
        self.fields["password2"] = forms.CharField(
            label="Confirm password",
            strip=False,
            widget=forms.PasswordInput(attrs=dict(attrs)),
        )

    def _validate_password_pair(self, cleaned_data, user):
        p1, p2 = cleaned_data.get("password1"), cleaned_data.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "The two passwords do not match.")
        elif p1:
            try:
                password_validation.validate_password(p1, user, password_validators=self._password_validators())
            except forms.ValidationError as error:
                self.add_error("password1", error)


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------
class PortalAuthenticationForm(BootstrapFormMixin, AuthenticationForm):
    """
    Login form for one portal. A valid account that belongs to the other
    portal gets the same generic error as a wrong password, so the form
    never reveals which accounts exist.
    """

    portal_roles = frozenset()

    error_messages = {
        **AuthenticationForm.error_messages,
        "invalid_login": "Incorrect login details, or this account cannot sign in here.",
        "locked": "Too many failed attempts. Please wait 15 minutes and try again.",
    }

    def clean(self):
        # Failures are counted in the authentication backend (shared with the
        # Django admin login); here we only show a clear message when locked.
        username = self.cleaned_data.get("username")
        if username and throttling.is_locked(self.request, username):
            raise forms.ValidationError(self.error_messages["locked"], code="locked")
        return super().clean()

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if user.role not in self.portal_roles:
            raise self.get_invalid_login_error()


class StaffLoginForm(PortalAuthenticationForm):
    portal_roles = STAFF_ROLES

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "Username or email"


class CustomerLoginForm(PortalAuthenticationForm):
    portal_roles = frozenset({Role.CUSTOMER})

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "Email address"
        self.fields["username"].widget.attrs.update({"autocomplete": "email", "inputmode": "email"})


# Django's password forms, with the LEO PRODUCTS styling.
class LeoPasswordChangeForm(BootstrapFormMixin, PasswordChangeForm):
    pass


class LeoPasswordResetForm(BootstrapFormMixin, PasswordResetForm):
    pass


class LeoSetPasswordForm(BootstrapFormMixin, SetPasswordForm):
    pass


# ---------------------------------------------------------------------------
# Customer registration and profiles
# ---------------------------------------------------------------------------
class CustomerRegistrationForm(BootstrapFormMixin, PasswordPairMixin, forms.ModelForm):
    """Public sign-up. Always creates a CUSTOMER, whatever the request contains."""

    # Simpler rules for customers only (see CUSTOMER_PASSWORD_VALIDATORS in settings).
    password_validators_setting = "CUSTOMER_PASSWORD_VALIDATORS"
    password_help_text = "Password must contain at least 6 characters."

    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "phone_number"]
        widgets = {
            "first_name": forms.TextInput(attrs={"autocomplete": "given-name"}),
            "last_name": forms.TextInput(attrs={"autocomplete": "family-name"}),
            "email": forms.EmailInput(attrs={"autocomplete": "email"}),
            "phone_number": forms.TextInput(attrs={"autocomplete": "tel", "inputmode": "tel"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._add_password_fields()
        for name in ("first_name", "last_name", "email", "phone_number"):
            self.fields[name].required = True

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if _email_taken(email):
            raise forms.ValidationError("An account with this email address already exists.")
        return email

    def clean(self):
        cleaned = super().clean()
        # Fill in the instance first so the similarity validator can compare.
        for name in ("first_name", "last_name", "email"):
            setattr(self.instance, name, cleaned.get(name, ""))
        self._validate_password_pair(cleaned, self.instance)
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.username = self.cleaned_data["email"]
        user.role = Role.CUSTOMER
        user.must_change_password = False
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user


class ProfileForm(BootstrapFormMixin, forms.ModelForm):
    """A user editing their own details. Role and status are not editable."""

    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "phone_number"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("first_name", "last_name", "email"):
            self.fields[name].required = True

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if _email_taken(email, exclude_pk=self.instance.pk):
            raise forms.ValidationError("Another account already uses this email address.")
        return email


# ---------------------------------------------------------------------------
# Staff management
# ---------------------------------------------------------------------------
class _StaffRoleMixin:
    def _limit_roles(self, actor):
        allowed = assignable_roles(actor)
        self.fields["role"].choices = [(r.value, r.label) for r in allowed]

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if _email_taken(email, exclude_pk=self.instance.pk):
            raise forms.ValidationError("Another account already uses this email address.")
        return email


class StaffCreateForm(BootstrapFormMixin, _StaffRoleMixin, PasswordPairMixin, forms.ModelForm):
    password_label = "Temporary password"

    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "email", "phone_number", "role"]

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        self.actor = actor
        self._limit_roles(actor)
        self._add_password_fields()
        for name in ("first_name", "last_name", "email"):
            self.fields[name].required = True
        self.fields["password1"].help_text = (
            "The staff member must replace this password the first time they sign in. "
            + self.fields["password1"].help_text
        )

    def clean(self):
        cleaned = super().clean()
        for name in ("username", "first_name", "last_name", "email"):
            setattr(self.instance, name, cleaned.get(name, ""))
        self._validate_password_pair(cleaned, self.instance)
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        if user.role not in assignable_roles(self.actor):  # defence in depth
            raise forms.ValidationError("You cannot assign this role.")
        user.must_change_password = True
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user


class StaffUpdateForm(BootstrapFormMixin, _StaffRoleMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "phone_number", "role"]

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        self.actor = actor
        self._limit_roles(actor)
        for name in ("first_name", "last_name", "email"):
            self.fields[name].required = True


class TemporaryPasswordForm(BootstrapFormMixin, PasswordPairMixin, forms.Form):
    """An authorised manager sets a temporary password for a staff member."""

    password_label = "New temporary password"

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self._add_password_fields()

    def clean(self):
        cleaned = super().clean()
        self._validate_password_pair(cleaned, self.user)
        return cleaned

    def save(self):
        self.user.set_password(self.cleaned_data["password1"])
        self.user.must_change_password = True
        self.user.save()
        return self.user


class StaffFilterForm(BootstrapFormMixin, forms.Form):
    q = forms.CharField(required=False, label="Search", widget=forms.TextInput(attrs={"placeholder": "Name, username or email", "type": "search"}))
    role = forms.ChoiceField(
        required=False,
        choices=[("", "All roles")] + [(r.value, r.label) for r in Role if r in STAFF_ROLES],
    )
    status = forms.ChoiceField(required=False, choices=[("", "Any status"), ("active", "Active"), ("inactive", "Inactive")])
