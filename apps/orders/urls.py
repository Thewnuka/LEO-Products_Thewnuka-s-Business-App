from django.urls import path

from . import views

app_name = "orders"

urlpatterns = [
    # Customer
    path("checkout/", views.CheckoutView.as_view(), name="checkout"),
    path("checkout/review/", views.CheckoutReviewView.as_view(), name="checkout_review"),
    path("account/orders/", views.MyOrdersView.as_view(), name="my_orders"),
    path("account/orders/<str:number>/", views.MyOrderDetailView.as_view(), name="detail"),
    path("account/orders/<str:number>/cancel/", views.MyOrderCancelView.as_view(), name="cancel"),

    # Staff
    path("staff/orders/", views.StaffOrderListView.as_view(), name="staff_list"),
    path("staff/orders/settings/", views.CheckoutSettingsView.as_view(), name="settings"),
    path("staff/orders/settings/zones/new/", views.ZoneCreateView.as_view(), name="zone_create"),
    path("staff/orders/settings/zones/<int:pk>/edit/", views.ZoneUpdateView.as_view(), name="zone_update"),
    path("staff/orders/<str:number>/", views.StaffOrderDetailView.as_view(), name="staff_detail"),
    path("staff/orders/<str:number>/status/", views.StaffStatusView.as_view(), name="staff_status"),
    path("staff/orders/<str:number>/cancel/", views.StaffCancelView.as_view(), name="staff_cancel"),
]
