from django.urls import path

from . import views

app_name = "catalog"

urlpatterns = [
    path("", views.CatalogDashboardView.as_view(), name="dashboard"),

    path("products/", views.ProductListView.as_view(), name="product_list"),
    path("products/new/", views.ProductCreateView.as_view(), name="product_create"),
    path("products/<int:pk>/", views.ProductDetailView.as_view(), name="product_detail"),
    path("products/<int:pk>/edit/", views.ProductUpdateView.as_view(), name="product_update"),
    path("products/<int:pk>/status/", views.ProductStatusView.as_view(), name="product_status"),

    path("products/<int:product_pk>/variations/", views.VariationListView.as_view(), name="variation_list"),
    path("products/<int:product_pk>/variations/new/", views.VariationCreateView.as_view(), name="variation_create"),
    path("products/<int:product_pk>/variations/<int:pk>/edit/", views.VariationUpdateView.as_view(), name="variation_update"),
    path("products/<int:product_pk>/variations/<int:pk>/toggle/", views.VariationToggleView.as_view(), name="variation_toggle"),

    path("categories/", views.CategoryListView.as_view(), name="category_list"),
    path("categories/new/", views.CategoryCreateView.as_view(), name="category_create"),
    path("categories/<int:pk>/edit/", views.CategoryUpdateView.as_view(), name="category_update"),
    path("categories/<int:pk>/toggle/", views.CategoryToggleView.as_view(), name="category_toggle"),
    path("categories/<int:pk>/delete/", views.CategoryDeleteView.as_view(), name="category_delete"),

    path("units/", views.UnitListView.as_view(), name="unit_list"),
    path("units/new/", views.UnitCreateView.as_view(), name="unit_create"),
    path("units/<int:pk>/edit/", views.UnitUpdateView.as_view(), name="unit_update"),
    path("units/<int:pk>/toggle/", views.UnitToggleView.as_view(), name="unit_toggle"),
]
