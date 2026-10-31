"""
Progressive Web App: install to home screen on Android/iPhone and desktop browsers.

  /manifest.webmanifest  name, colours, icons (from the official logo), standalone display
  /sw.js                 service worker (served from the site root so it covers the whole site)
  /offline/              page shown when there is no connection (contains no user data)

The service worker ONLY caches static files (CSS, JavaScript, icons, fonts). Pages, account
data, orders, payments, reports and uploads are never cached: they always come from the
server, so nothing private is ever stored on the device by the app.
"""
import hashlib
import json

from django.conf import settings
from django.contrib.staticfiles import finders
from django.http import HttpResponse
from django.shortcuts import render
from django.templatetags.static import static
from django.urls import reverse
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_GET

THEME_COLOR = "#123d28"
BACKGROUND_COLOR = "#f7f5ef"

# Files every page uses: cached when the app is installed, so it starts fast and works offline.
PRECACHE = [
    "css/leo.css", "js/leo.js", "js/pwa.js", "images/leo-logo.png",
    "vendor/bootstrap/css/bootstrap.min.css", "vendor/bootstrap/js/bootstrap.bundle.min.js",
    "vendor/bootstrap-icons/bootstrap-icons.min.css",
    "vendor/bootstrap-icons/fonts/bootstrap-icons.woff2", "vendor/bootstrap-icons/fonts/bootstrap-icons.woff",
    "icons/icon-192.png", "icons/icon-512.png", "icons/favicon-32.png",
]


def _version(paths):
    """Changes whenever a pre-cached file changes, so installed apps pick up new CSS/JS."""
    digest = hashlib.sha256()
    for path in paths:
        digest.update(static(path).encode())
        found = finders.find(path)
        if found:
            with open(found, "rb") as handle:
                digest.update(hashlib.sha256(handle.read()).digest())
    return digest.hexdigest()[:12]


@require_GET
@cache_control(max_age=86400, public=True)
def manifest(request):
    brand = settings.BRAND
    data = {
        "name": brand["NAME"],
        "short_name": "LEO",
        "description": brand["TAGLINE"],
        "lang": "en",
        "start_url": "/?source=app",
        "scope": "/",
        "display": "standalone",
        "orientation": "any",
        "theme_color": THEME_COLOR,
        "background_color": BACKGROUND_COLOR,
        "icons": [
            {"src": static("icons/icon-192.png"), "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": static("icons/icon-512.png"), "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {"src": static("icons/icon-maskable-512.png"), "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
        "shortcuts": [
            {"name": "Shop", "url": reverse("shop:home")},
            {"name": "Staff portal", "url": reverse("accounts:staff_login")},
        ],
    }
    return HttpResponse(json.dumps(data, indent=2), content_type="application/manifest+json")


@require_GET
@cache_control(no_cache=True)   # browsers must re-check the worker on every visit, so updates arrive
def service_worker(request):
    response = render(request, "pwa/sw.js", {
        "version": _version(PRECACHE), "precache": [static(p) for p in PRECACHE],
        "static_prefix": settings.STATIC_URL if settings.STATIC_URL.startswith("/") else "/" + settings.STATIC_URL,
        "offline_url": reverse("core:offline"),
    }, content_type="application/javascript")
    response["Service-Worker-Allowed"] = "/"
    return response


@require_GET
def offline(request):
    """Shown by the service worker when there is no connection. Deliberately has no user-specific content."""
    return render(request, "pwa/offline.html")
