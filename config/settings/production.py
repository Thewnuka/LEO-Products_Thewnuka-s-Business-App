"""
Production settings.

DEBUG is always off here and cannot be switched on by an environment variable.
Required environment variables: SECRET_KEY, ALLOWED_HOSTS, DATABASE_URL.
See deploy/env.production.example and DEVELOPMENT_GUIDE ("Going live").
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

# Single shop PC mode: the server only listens on this computer (http://127.0.0.1) and is used
# through the desktop app or a browser on the same PC. HTTPS isn't possible there, so secure-only
# cookies and the HTTPS redirect are relaxed. Refused unless every allowed host is local.
LOCAL_HTTP_ONLY = env_bool("LOCAL_HTTP_ONLY", False)
if LOCAL_HTTP_ONLY:
    from django.core.exceptions import ImproperlyConfigured

    if not ALLOWED_HOSTS or set(ALLOWED_HOSTS) - {"127.0.0.1", "localhost"}:  # noqa: F405
        raise ImproperlyConfigured("LOCAL_HTTP_ONLY=True is only allowed when ALLOWED_HOSTS=127.0.0.1,localhost.")
    SECURE_SSL_REDIRECT = SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = False
    SECURE_HSTS_SECONDS = 0

# Needed when Django runs behind a reverse proxy (Nginx, a hosting platform)
# that terminates HTTPS and forwards requests over HTTP.
if env_bool("USE_X_FORWARDED_PROTO", False):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# ---------------------------------------------------------------------------
# Static files: served by WhiteNoise (compressed, cache-busting names, long cache).
# Run `python manage.py collectstatic` on every deployment.
# ---------------------------------------------------------------------------
MIDDLEWARE = list(MIDDLEWARE)  # noqa: F405
MIDDLEWARE.insert(MIDDLEWARE.index("django.middleware.security.SecurityMiddleware") + 1,
                  "whitenoise.middleware.WhiteNoiseMiddleware")
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# Uploaded product images (MEDIA_ROOT) are normally served by the web server (see deploy/nginx.conf.example).
# On a single Windows PC without a web server, set SERVE_MEDIA=True to let Django serve them.
# Payment slips and expense receipts (PRIVATE_MEDIA_ROOT) are NEVER served directly in any case.
SERVE_MEDIA = env_bool("SERVE_MEDIA", False)

# ---------------------------------------------------------------------------
# Database: keep connections open and check them before reuse (PostgreSQL).
# ---------------------------------------------------------------------------
DATABASES["default"]["CONN_MAX_AGE"] = int(os.getenv("DB_CONN_MAX_AGE", "600"))  # noqa: F405
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True  # noqa: F405

# ---------------------------------------------------------------------------
# Logging: everything at WARNING and above goes to the console (captured by
# systemd / the hosting platform / the Windows service wrapper).
# ---------------------------------------------------------------------------
LOGGING["root"] = {"handlers": ["console"], "level": os.getenv("LOG_LEVEL", "WARNING")}  # noqa: F405
