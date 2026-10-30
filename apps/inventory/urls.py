from django.urls import path

from . import views

app_name = "inventory"

urlpatterns = [
    path("", views.InventoryDashboardView.as_view(), name="dashboard"),

    path("items/", views.ItemListView.as_view(), name="item_list"),
    path("items/new/", views.ItemCreateView.as_view(), name="item_create"),
    path("items/<int:pk>/", views.ItemDetailView.as_view(), name="item_detail"),
    path("items/<int:pk>/edit/", views.ItemUpdateView.as_view(), name="item_update"),
    path("items/<int:pk>/adjust/", views.StockAdjustView.as_view(), name="item_adjust"),
    path("movements/", views.MovementListView.as_view(), name="movement_list"),

    path("suppliers/", views.SupplierListView.as_view(), name="supplier_list"),
    path("suppliers/new/", views.SupplierCreateView.as_view(), name="supplier_create"),
    path("suppliers/<int:pk>/", views.SupplierDetailView.as_view(), name="supplier_detail"),
    path("suppliers/<int:pk>/edit/", views.SupplierUpdateView.as_view(), name="supplier_update"),
    path("suppliers/<int:pk>/toggle/", views.SupplierToggleView.as_view(), name="supplier_toggle"),

    path("purchases/", views.PurchaseListView.as_view(), name="purchase_list"),
    path("purchases/new/", views.PurchaseCreateView.as_view(), name="purchase_create"),
    path("purchases/<int:pk>/", views.PurchaseDetailView.as_view(), name="purchase_detail"),
    path("purchases/<int:pk>/edit/", views.PurchaseUpdateView.as_view(), name="purchase_update"),
    path("purchases/<int:pk>/receive/", views.PurchaseReceiveView.as_view(), name="purchase_receive"),
    path("purchases/<int:pk>/cancel/", views.PurchaseCancelView.as_view(), name="purchase_cancel"),
]
