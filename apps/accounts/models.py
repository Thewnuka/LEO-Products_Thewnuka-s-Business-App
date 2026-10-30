from django.contrib.auth.models import AbstractUser, UserManager
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower

from apps.core.models import TimeStampedModel

from .roles import STAFF_ROLES, Role, has_capability

phone_validator = RegexValidator(
    regex=r"^\+?[0-9 ()-]{7,20}$",
    message="Enter a valid phone number (digits, spaces, +, - and brackets only).",
)


def identifier_taken(value, exclude_pk=None):
    """True if `value` is another account's username or email (case-insensitive)."""
    qs = User.objects.filter(Q(username__iexact=value) | Q(email__iexact=value))
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    return qs.exists()


class LeoUserManager(UserManager):
    def create_superuser(self, username, email=None, password=None, **extra_fields):
        # `createsuperuser` makes an OWNER (not the primary owner; use bootstrap_owner for that).
        extra_fields.setdefault("role", Role.OWNER)
        return super().create_superuser(username, email, password, **extra_fields)


class User(AbstractUser):
    """
    Custom user model for LEO PRODUCTS.

    Each user has exactly one primary role (see apps/accounts/roles.py).
    Django's own is_staff / is_superuser flags are derived from the role
    on every save: only OWNER accounts may use the Django admin site.
    """

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.CUSTOMER, db_index=True)
    phone_number = models.CharField(max_length=20, blank=True, validators=[phone_validator])
    must_change_password = models.BooleanField(
        default=False,
        help_text="If set, the user must choose a new password before using the system.",
    )
    is_primary_owner = models.BooleanField(
        default=False,
        editable=False,
        help_text="The original owner account. It cannot be deleted, deactivated or demoted.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    objects = LeoUserManager()

    class Meta(AbstractUser.Meta):
        db_table = "accounts_user"
        verbose_name = "user"
        verbose_name_plural = "users"
        constraints = [
            # Case-insensitive unique email, while still allowing blank emails.
            models.UniqueConstraint(
                Lower("email"),
                condition=~Q(email=""),
                name="accounts_user_unique_email_ci",
                violation_error_message="A user with this email address already exists.",
            ),
            models.UniqueConstraint(
                fields=["is_primary_owner"],
                condition=Q(is_primary_owner=True),
                name="accounts_user_single_primary_owner",
            ),
        ]

    def __str__(self):
        return self.get_full_name() or self.username

    # ----- role helpers ------------------------------------------------------
    @property
    def is_staff_member(self):
        return self.role in STAFF_ROLES

    @property
    def is_customer(self):
        return self.role == Role.CUSTOMER

    def has_capability(self, capability):
        return has_capability(self, capability)

    @property
    def portal_home_url(self):
        from .routing import home_url_for

        return home_url_for(self)

    # ----- integrity ---------------------------------------------------------
    def clean(self):
        super().clean()
        self.email = (self.email or "").strip().lower()
        if self.is_primary_owner and (self.role != Role.OWNER or not self.is_active):
            raise ValidationError("The primary owner account must stay active with the OWNER role.")
        # People sign in with a username OR an email, so neither may match
        # another account's username or email (ignoring case).
        errors = {}
        if self.username and identifier_taken(self.username, exclude_pk=self.pk):
            errors["username"] = "This username is already used by another account (as a username or email)."
        if self.email and identifier_taken(self.email, exclude_pk=self.pk):
            errors["email"] = "Another account already uses this email address."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.is_primary_owner and (self.role != Role.OWNER or not self.is_active):
            raise ValidationError("The primary owner account must stay active with the OWNER role.")
        self.email = (self.email or "").strip().lower()
        # Django admin access follows the role; it is never set independently.
        self.is_staff = self.is_superuser = self.role == Role.OWNER
        if kwargs.get("update_fields") is not None:
            kwargs["update_fields"] = set(kwargs["update_fields"]) | {"is_staff", "is_superuser", "email"}
        super().save(*args, **kwargs)


class AccountAuditLog(TimeStampedModel):
    """
    Record of important account changes. Never stores passwords or tokens.

    Kept deliberately simple so a later phase can move it into a
    project-wide audit log.
    """

    class Action(models.TextChoices):
        OWNER_BOOTSTRAPPED = "owner_bootstrapped", "Primary owner created"
        CUSTOMER_REGISTERED = "customer_registered", "Customer registered"
        STAFF_CREATED = "staff_created", "Staff account created"
        STAFF_UPDATED = "staff_updated", "Staff details updated"
        ROLE_CHANGED = "role_changed", "Role changed"
        ACTIVATED = "activated", "Account activated"
        DEACTIVATED = "deactivated", "Account deactivated"
        PASSWORD_SET_BY_ADMIN = "password_set_by_admin", "Temporary password set"
        PASSWORD_CHANGED = "password_changed", "Password changed"
        PASSWORD_RESET = "password_reset", "Password reset by email link"
        PROFILE_UPDATED = "profile_updated", "Own profile updated"

    action = models.CharField(max_length=40, choices=Action.choices, db_index=True)
    actor = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="audit_actions",
        help_text="Who made the change (empty for system actions).",
    )
    target = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="audit_events",
        help_text="The account that was changed.",
    )
    details = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta(TimeStampedModel.Meta):
        verbose_name = "account audit entry"
        verbose_name_plural = "account audit log"

    def __str__(self):
        return f"{self.get_action_display()} ({self.created_at:%Y-%m-%d %H:%M})"
