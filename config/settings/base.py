"""
Shared Django settings for LEO PRODUCTS.

Values that differ between machines (secrets, hosts, database) are read
from environment variables. Locally they come from the `.env` file.
"""
from pathlib import Path
import os

import dj_database_url
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

# Project root: the folder that contains manage.py
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Load variables from .env (never committed to Git).
load_dotenv(BASE_DIR / ".env")


def env_bool(name, default=False):
    """Read an environment variable as True/False."""
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name, default=""):
    """Read a comma-separated environment variable as a list."""
    value = os.getenv(name, default)
    return [item.strip() for item in value.split(",") if item.strip()]


def env_required(name):
    """Read an environment variable that must be set."""
    value = os.getenv(name)
    if not value:
        raise ImproperlyConfigured(f"The {name} environment variable is required.")
    return value


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------
SECRET_KEY = env_required("SECRET_KEY")
DEBUG = False
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")

APP_VERSION = "0.1.0"

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "drf_spectacular",
]

# Business apps live in apps/. Future phases add theirs here.
LOCAL_APPS = [
    "apps.core",
    "apps.accounts",
    "apps.dashboard",
    "apps.catalog",
    "apps.inventory",
    "apps.shop",
    "apps.orders",
    "apps.payments",
    "apps.pos",
    "apps.finance",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "apps.accounts.middleware.ForcePasswordChangeMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.brand",
                "apps.accounts.context_processors.access",
                "apps.shop.context_processors.cart",
            ],
        },
    },
]

# ---------------------------------------------------------------------------
# Database
# SQLite by default; set DATABASE_URL to use PostgreSQL, e.g.
# postgres://USER:PASSWORD@HOST:5432/NAME
# ---------------------------------------------------------------------------
# An empty DATABASE_URL (as in .env.example) also falls back to SQLite.
DATABASE_URL = os.getenv("DATABASE_URL") or f"sqlite:///{(BASE_DIR / 'db.sqlite3').as_posix()}"

DATABASES = {
    "default": dj_database_url.parse(
        DATABASE_URL,
        conn_max_age=int(os.getenv("DB_CONN_MAX_AGE", "60")),
    )
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Authentication
# The custom user model must exist before the first migration.
# ---------------------------------------------------------------------------
AUTH_USER_MODEL = "accounts.User"

# Sign in with username or email. Django's password hashing (PBKDF2-SHA256)
# is used for every password; plaintext passwords are never stored.
AUTHENTICATION_BACKENDS = ["apps.accounts.backends.EmailOrUsernameModelBackend"]

LOGIN_URL = "accounts:customer_login"
LOGIN_REDIRECT_URL = "accounts:login_redirect"  # sends each role to its own home
LOGOUT_REDIRECT_URL = "core:home"

# Password reset links expire after 1 hour (Django's default is 3 days).
PASSWORD_RESET_TIMEOUT = 60 * 60

# Login throttling (see apps/accounts/throttling.py)
LOGIN_RATE_LIMIT_ATTEMPTS = int(os.getenv("LOGIN_RATE_LIMIT_ATTEMPTS", "5"))
LOGIN_RATE_LIMIT_WINDOW = int(os.getenv("LOGIN_RATE_LIMIT_WINDOW", str(15 * 60)))

# In-memory cache per server process. A shared cache (e.g. Redis or the
# database) should be configured in production so limits apply across workers.
CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "leo-default"},
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Simpler rule for public CUSTOMER registration only: at least 6 characters.
# Staff accounts, temporary passwords and password change/reset keep the
# stricter AUTH_PASSWORD_VALIDATORS above. Hashing is identical for everyone.
CUSTOMER_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 6}},
]

# ---------------------------------------------------------------------------
# Internationalization
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = os.getenv("TIME_ZONE", "Asia/Colombo")
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Static files (CSS, JS, images shipped with the code)
# Media files (uploads made by users, e.g. product photos, logo uploads)
# ---------------------------------------------------------------------------
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# Size limit for non-file form data. (Uploaded files are NOT counted here.)
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
# Uploads bigger than this are buffered to a temporary file instead of memory.
# It does not reject anything; file size limits are checked by each upload
# validator (e.g. CATALOG_IMAGE_MAX_BYTES) and, in production, the web server.
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024

# Catalogue images (see apps/catalog/images.py)
CATALOG_IMAGE_MAX_BYTES = 5 * 1024 * 1024  # 5 MB per image
CATALOG_IMAGE_MAX_SIDE = 1600              # stored images are shrunk to fit 1600 × 1600 px

# Money is stored as Decimal; all catalogue prices are in this currency.
CURRENCY_CODE = "LKR"

# Online shop (Phase 05)
CART_MAX_QUANTITY_PER_ITEM = 50   # most of one item a customer can put in the cart
SHOP_LOW_STOCK_THRESHOLD = 5      # show "Only N left" at or below this many
SHOP_PAGE_SIZE = 12

# Orders & payments (Phase 06)
# Payment evidence (bank-transfer slips) is stored here, NOT under MEDIA_ROOT,
# so it is never publicly reachable. Back it up together with the database.
PRIVATE_MEDIA_ROOT = Path(os.getenv("PRIVATE_MEDIA_ROOT", str(BASE_DIR / "private_media")))
PAYMENT_EVIDENCE_MAX_BYTES = 5 * 1024 * 1024
ORDER_PAGE_SIZE = 20

# Online payment gateway. Empty = online payment switched off (no fake payments).
# Supported: "payhere". Credentials only come from the environment (.env).
PAYMENT_GATEWAY = os.getenv("PAYMENT_GATEWAY", "").strip().lower()
PAYHERE_MERCHANT_ID = os.getenv("PAYHERE_MERCHANT_ID", "")
PAYHERE_MERCHANT_SECRET = os.getenv("PAYHERE_MERCHANT_SECRET", "")
PAYHERE_SANDBOX = env_bool("PAYHERE_SANDBOX", True)

# ---------------------------------------------------------------------------
# Security foundations (production.py adds HTTPS-only settings)
# ---------------------------------------------------------------------------
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = int(os.getenv("SESSION_COOKIE_AGE", str(60 * 60 * 8)))  # 8 hours
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
CSRF_COOKIE_SAMESITE = "Lax"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# Admin lives at a configurable path so it is not at the predictable /admin/.
ADMIN_URL = os.getenv("ADMIN_URL", "admin/").strip("/") + "/"

# ---------------------------------------------------------------------------
# Brand
# The single source of truth for brand identity. Templates read it through
# the `brand` context processor. A later phase can let authorised staff
# override these values (including uploading a new logo) from a Business
# Settings screen without changing any template.
# ---------------------------------------------------------------------------
BRAND = {
    "NAME": "LEO PRODUCTS",
    "TAGLINE": "taste of tradition, zip of purity",
    # Official LEO PRODUCTS logo (path inside static/). Replace the file to change it everywhere.
    "LOGO": "images/leo-logo.png",
    "LOGO_IS_PLACEHOLDER": False,
}

# ---------------------------------------------------------------------------
# Email (configured in a future phase; console backend prints to terminal)
# ---------------------------------------------------------------------------
EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = os.getenv("EMAIL_HOST", "")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "LEO PRODUCTS <no-reply@localhost>")

# ---------------------------------------------------------------------------
# Django REST Framework
# Secure by default: every future endpoint requires login unless it
# explicitly opts out (like the health check).
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "LEO PRODUCTS API",
    "DESCRIPTION": "Backend API shared by the web app, the Windows desktop app and the PWA.",
    "VERSION": APP_VERSION,
    "SERVE_INCLUDE_SCHEMA": False,
}

# ---------------------------------------------------------------------------
# Logging: errors go to the console (captured by the server in production).
# ---------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": os.getenv("LOG_LEVEL", "INFO")},
}
