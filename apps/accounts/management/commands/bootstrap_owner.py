"""
Create the primary OWNER account, safely and repeatably.

    python manage.py bootstrap_owner

Credentials come from environment variables, or are asked for interactively:
    OWNER_USERNAME, OWNER_EMAIL, OWNER_PASSWORD

Rules:
- Runs once: if a primary owner already exists, nothing is changed.
- Never changes an existing password.
- The new owner must change the password at first sign-in.
- The password is hashed by Django and never printed or logged.
"""
import getpass
import os

from django.conf import settings
from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Q

from apps.accounts import audit
from apps.accounts.models import AccountAuditLog, User
from apps.accounts.roles import Role


class Command(BaseCommand):
    help = "Create the primary OWNER account (idempotent; never resets an existing password)."

    def add_arguments(self, parser):
        parser.add_argument("--username", help="Overrides OWNER_USERNAME.")
        parser.add_argument("--email", help="Overrides OWNER_EMAIL.")
        parser.add_argument("--no-input", action="store_true", help="Never prompt; fail if a value is missing.")
        parser.add_argument(
            "--promote-existing",
            action="store_true",
            help="If the username/email already belongs to an account, make that account the primary "
                 "owner. Its password is left unchanged.",
        )
        parser.add_argument(
            "--allow-weak-password",
            action="store_true",
            help="Development only (DEBUG=True): accept a temporary password that fails the password "
                 "rules. It must be changed at first sign-in anyway.",
        )

    def handle(self, *args, **opts):
        existing_owner = User.objects.filter(is_primary_owner=True).first()
        if existing_owner:
            self.stdout.write(self.style.WARNING(
                f"A primary owner already exists (username '{existing_owner.username}'). No changes made."
            ))
            return

        interactive = not opts["no_input"]
        username = (opts["username"] or os.getenv("OWNER_USERNAME") or "").strip()
        email = (opts["email"] or os.getenv("OWNER_EMAIL") or "").strip().lower()
        if not username and interactive:
            username = input("Owner username: ").strip()
        if not email and interactive:
            email = input("Owner email: ").strip().lower()
        if not username or not email:
            raise CommandError("Username and email are required (set OWNER_USERNAME and OWNER_EMAIL).")
        try:
            validate_email(email)
        except ValidationError:
            raise CommandError("OWNER_EMAIL is not a valid email address.")

        match = User.objects.filter(Q(username=username) | Q(email__iexact=email)).first()
        if match:
            self._promote(match, opts["promote_existing"])
            return

        password = os.getenv("OWNER_PASSWORD") or ""
        if not password and interactive:
            password = getpass.getpass("Temporary owner password: ")
            if password != getpass.getpass("Confirm password: "):
                raise CommandError("Passwords do not match.")
        if not password:
            raise CommandError("A password is required (set OWNER_PASSWORD or run interactively).")

        user = User(username=username, email=email, role=Role.OWNER)
        try:
            password_validation.validate_password(password, user)
        except ValidationError as error:
            if not opts["allow_weak_password"]:
                raise CommandError(
                    "Password rejected: " + " ".join(error.messages)
                    + " (development only: add --allow-weak-password)"
                )
            if not settings.DEBUG:
                raise CommandError("--allow-weak-password is only permitted when DEBUG=True.")
            self.stdout.write(self.style.WARNING(
                "Weak temporary password accepted for development. It must be changed at first sign-in."
            ))

        with transaction.atomic():
            user.is_primary_owner = True
            user.must_change_password = True
            user.set_password(password)
            user.save()
            audit.record(AccountAuditLog.Action.OWNER_BOOTSTRAPPED, target=user, method="bootstrap_owner")

        self.stdout.write(self.style.SUCCESS(
            f"Primary owner '{username}' created. Sign in at /staff/login/; "
            "a new password will be required at first sign-in."
        ))

    def _promote(self, user, allowed):
        if not allowed:
            raise CommandError(
                f"An account with this username or email already exists ('{user.username}'). "
                "Nothing was changed. To make it the primary owner, re-run with --promote-existing."
            )
        with transaction.atomic():
            user.role = Role.OWNER
            user.is_active = True
            user.is_primary_owner = True
            user.save()
            audit.record(AccountAuditLog.Action.OWNER_BOOTSTRAPPED, target=user, method="promote_existing")
        self.stdout.write(self.style.SUCCESS(
            f"Existing account '{user.username}' is now the primary owner. Its password was not changed."
        ))
