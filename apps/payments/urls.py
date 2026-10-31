from django.urls import path

from . import views

app_name = "payments"

urlpatterns = [
    path("account/orders/<str:number>/pay/bank-transfer/", views.SubmitBankTransferView.as_view(), name="bank_submit"),
    path("account/orders/<str:number>/pay/online/", views.StartOnlinePaymentView.as_view(), name="online_start"),
    path("payments/return/<str:reference>/", views.OnlineReturnView.as_view(), name="online_return"),
    path("payments/cancel/<str:reference>/", views.OnlineCancelView.as_view(), name="online_cancel"),
    path("payments/webhook/<slug:gateway>/", views.GatewayWebhookView.as_view(), name="webhook"),
    path("payments/<str:reference>/evidence/", views.EvidenceView.as_view(), name="evidence"),
    path("staff/payments/<str:reference>/review/", views.ReviewBankTransferView.as_view(), name="review"),
    path("staff/orders/<str:number>/cash/", views.RecordCashView.as_view(), name="record_cash"),
    path("staff/payments/<str:reference>/refund/", views.RecordRefundView.as_view(), name="refund"),
]
