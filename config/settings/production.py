"""
Production settings.

DEBUG is always off here and cannot be switched on by an environment variable.
Required environment variables: SECRET_KEY, ALLOWED_HOSTS, DATABASE_URL.
"""
import os

from .base import *  # noqa: F401,F403
from .base import env_bool, env_required

DEBUG = False

# Fail loudly instead of silently starting with unsafe defaults.
env_required("ALLOWED_HOSTS")
env_required("DATABASE_URL")

# ---------------------------------------------------------------------------
# HTTPS hardening
# ---------------------------------------------------------------------------
SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", True)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "3600"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", False)
SECURE_HSTS_PRELOAD = False

# Needed when Django runs behind a reverse proxy (Nginx, a hosting platform)
# that terminates HTTPS and forwards requests over HTTP.
if env_bool("USE_X_FORWARDED_PROTO", False):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Cache-busting file names for CSS/JS after `collectstatic`.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.ManifestStaticFilesStorage"},
}
