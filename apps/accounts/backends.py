from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.core.exceptions import PermissionDenied

from . import throttling


class EmailOrUsernameModelBackend(ModelBackend):
    """
    Sign in with either username or email address (case-insensitive email).

    Inherits Django's checks: inactive users cannot sign in, and their
    existing sessions stop working on the next request.

    Brute-force protection lives here (not in a form) so that every sign-in
    page shares it: both portals and the Django admin login.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        UserModel = get_user_model()
        if username is None:
            username = kwargs.get(UserModel.USERNAME_FIELD)
        if not username or password is None:
            return None
        username = username.strip()

        if throttling.is_locked(request, username):
            # Stops Django trying any other backend; the form shows an error.
            raise PermissionDenied("Too many failed sign-in attempts.")

        user = self._find_user(UserModel, username)
        if user is None:
            # Run the hasher anyway so response time does not reveal
            # whether the account exists.
            UserModel().set_password(password)
        elif user.check_password(password) and self.user_can_authenticate(user):
            throttling.reset(request, username)
            return user

        throttling.register_failure(request, username)
        return None

    @staticmethod
    def _find_user(UserModel, username):
        user = UserModel._default_manager.filter(username=username).first()
        if user is None and "@" in username:
            user = UserModel._default_manager.filter(email__iexact=username).first()
        return user
