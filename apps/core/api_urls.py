"""
Versioned API routes (/api/v1/...).

Future apps add their API routes here, e.g.
    path("catalog/", include("apps.catalog.api_urls")),
"""
from django.urls import include, path

from .api import HealthCheckView

app_name = "api"

urlpatterns = [
    path("health/", HealthCheckView.as_view(), name="health"),
    path("accounts/", include("apps.accounts.api_urls")),  # api:me
    path("catalog/", include("apps.catalog.api_urls")),    # api:catalog-product-list, ...
    path("inventory/", include("apps.inventory.api_urls")),  # api:inventory-item-list, ...
]
