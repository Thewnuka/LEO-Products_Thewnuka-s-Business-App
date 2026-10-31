"""
Extra security headers for every response.

Content-Security-Policy: the browser may only run scripts from this site (no inline
scripts, no third-party JavaScript), load styles from this site and Google Fonts, and
submit forms to this site or the configured payment gateway. This blocks most
cross-site scripting even if a bug ever let untrusted HTML into a page.

Permissions-Policy: the site never needs the camera, microphone, location etc.

Cache-Control for signed-in users: pages with personal or business data are never stored by
the browser or any proxy (so they can't be shown again from cache after signing out, on a
shared computer, or while offline).
"""
from django.conf import settings
from django.utils.cache import add_never_cache_headers

GATEWAY_FORM_TARGETS = {
    "payhere": "https://sandbox.payhere.lk https://www.payhere.lk",
}

# Debug-only tools that load their own inline scripts/CDN files (never available in production).
EXEMPT_PREFIXES = ("/api/docs/", "/api/schema/")


def build_csp():
    form_action = "'self'"
    gateway = GATEWAY_FORM_TARGETS.get(getattr(settings, "PAYMENT_GATEWAY", ""))
    if gateway:
        form_action += " " + gateway
    return "; ".join([
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self' https://fonts.googleapis.com",
        "style-src-attr 'unsafe-inline'",   # style="" attributes only (no <style> blocks, no scripts)
        "font-src 'self' https://fonts.gstatic.com data:",
        "img-src 'self' data: blob:",
        "connect-src 'self'",
        "manifest-src 'self'",
        "worker-src 'self'",
        f"form-action {form_action}",
        "frame-ancestors 'none'",
        "base-uri 'self'",
        "object-src 'none'",
    ])


PERMISSIONS_POLICY = "camera=(), microphone=(), geolocation=(), usb=(), payment=()"


class SecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.csp = build_csp()

    def __call__(self, request):
        response = self.get_response(request)
        if settings.DEBUG and request.path.startswith(EXEMPT_PREFIXES):
            return response
        response.headers.setdefault("Content-Security-Policy", self.csp)
        response.headers.setdefault("Permissions-Policy", PERMISSIONS_POLICY)
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and "Cache-Control" not in response:
            add_never_cache_headers(response)  # no-cache, no-store, must-revalidate, private
        return response
