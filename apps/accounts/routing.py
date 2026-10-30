"""Where each role lands after signing in."""
from django.urls import reverse

from .roles import Role

ROLE_HOME_URL_NAMES = {
    Role.OWNER: "dashboard:owner",
    Role.IT_ADMIN: "dashboard:it_admin",
    Role.MANAGER: "dashboard:manager",
    Role.CASHIER: "dashboard:cashier",
    Role.CUSTOMER: "accounts:customer_home",
}


def home_url_for(user):
    if not (user and user.is_authenticated):
        return reverse("core:home")
    return reverse(ROLE_HOME_URL_NAMES.get(user.role, "core:home"))
