from django.urls import path

from . import views

app_name = "pos"

urlpatterns = [
    path("staff/pos/", views.TerminalView.as_view(), name="terminal"),
    path("staff/pos/shift/open/", views.OpenShiftView.as_view(), name="shift_open"),
    path("staff/pos/sale/", views.CheckoutView.as_view(), name="checkout"),
    path("staff/pos/sales/", views.SalesListView.as_view(), name="sales"),
    path("staff/pos/sales/<str:number>/", views.SaleDetailView.as_view(), name="sale_detail"),
    path("staff/pos/sales/<str:number>/receipt/", views.ReceiptView.as_view(), name="receipt"),
    path("staff/pos/sales/<str:number>/reprint/", views.ReprintView.as_view(), name="reprint"),
    path("staff/pos/sales/<str:number>/refund/", views.RefundView.as_view(), name="refund"),
    path("staff/pos/shifts/", views.ShiftListView.as_view(), name="shifts"),
    path("staff/pos/shifts/<int:pk>/", views.ShiftDetailView.as_view(), name="shift_detail"),
    path("staff/pos/shifts/<int:pk>/cash/", views.CashMovementView.as_view(), name="cash_movement"),
    path("staff/pos/shifts/<int:pk>/close/", views.CloseShiftView.as_view(), name="shift_close"),
    path("staff/pos/settings/", views.PosSettingsView.as_view(), name="settings"),
]
