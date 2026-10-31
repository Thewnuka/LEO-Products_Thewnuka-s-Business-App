from django.urls import path

from . import views

app_name = "finance"

urlpatterns = [
    path("", views.FinanceDashboardView.as_view(), name="dashboard"),
    path("reports/", views.ReportsIndexView.as_view(), name="reports"),
    path("reports/<slug:slug>/", views.ReportView.as_view(), name="report"),
    path("expenses/", views.ExpenseListView.as_view(), name="expenses"),
    path("expenses/new/", views.ExpenseCreateView.as_view(), name="expense_create"),
    path("expenses/<int:pk>/", views.ExpenseDetailView.as_view(), name="expense_detail"),
    path("expenses/<int:pk>/receipt/", views.ExpenseReceiptView.as_view(), name="expense_receipt"),
    path("expenses/<int:pk>/void/", views.ExpenseVoidView.as_view(), name="expense_void"),
    path("expense-categories/", views.CategoryListView.as_view(), name="categories"),
    path("expense-categories/new/", views.CategoryCreateView.as_view(), name="category_create"),
    path("expense-categories/<int:pk>/edit/", views.CategoryUpdateView.as_view(), name="category_update"),
    path("supplier-payments/", views.SupplierPaymentListView.as_view(), name="supplier_payments"),
    path("supplier-payments/new/", views.SupplierPaymentCreateView.as_view(), name="supplier_payment_create"),
    path("supplier-payments/<int:pk>/void/", views.SupplierPaymentVoidView.as_view(), name="supplier_payment_void"),
    path("suppliers/<int:pk>/statement/", views.SupplierStatementView.as_view(), name="supplier_statement"),
    path("stock-costs/", views.StockCostListView.as_view(), name="stock_costs"),
    path("stock-costs/<int:pk>/", views.StockCostSetView.as_view(), name="stock_cost"),
    path("audit-log/", views.AuditLogView.as_view(), name="audit_log"),
]
