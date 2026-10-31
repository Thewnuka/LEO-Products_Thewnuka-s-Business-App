"""
Root URL configuration for LEO PRODUCTS.

Each app owns its own urls.py; this file only connects them.
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path(settings.ADMIN_URL, admin.site.urls),
    path("api/v1/", include("apps.core.api_urls")),
    path("staff/dashboard/", include("apps.dashboard.urls")),
    path("staff/catalog/", include("apps.catalog.urls")),
    path("staff/inventory/", include("apps.inventory.urls")),
    path("staff/finance/", include("apps.finance.urls")),
    path("", include("apps.shop.urls")),       # /shop/... and /cart/...
    path("", include("apps.orders.urls")),     # /checkout/, /account/orders/, /staff/orders/
    path("", include("apps.payments.urls")),   # /payments/..., payment actions
    path("", include("apps.pos.urls")),        # /staff/pos/... point of sale
    path("", include("apps.notifications.urls")),  # /notifications/, /staff/alerts/
    path("", include("apps.accounts.urls")),
    path("", include("apps.core.urls")),
]

if settings.DEBUG:
    from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

    urlpatterns += [
        path("api/schema/", SpectacularAPIView.as_view(), name="api-schema"),
        path("api/docs/", SpectacularSwaggerView.as_view(url_name="api-schema"), name="api-docs"),
    ]
    # In production, the web server serves uploaded media files instead.
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
elif getattr(settings, "SERVE_MEDIA", False):
    # Single-server installs without Nginx (see production.py). Public product images only;
    # PRIVATE_MEDIA_ROOT (payment slips, receipts) is a different folder and is never exposed.
    from django.urls import re_path
    from django.views.static import serve

    urlpatterns += [re_path(rf"^{settings.MEDIA_URL.strip('/')}/(?P<path>.*)$", serve,
                            {"document_root": settings.MEDIA_ROOT})]

# Branded error pages (templates/400.html, 403.html, 404.html, 500.html)
handler400 = "apps.core.views.bad_request"
handler403 = "apps.core.views.permission_denied"
handler404 = "apps.core.views.page_not_found"
handler500 = "apps.core.views.server_error"
