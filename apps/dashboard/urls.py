from django.urls import path

from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.DashboardRedirectView.as_view(), name="home"),
    path("owner/", views.OwnerDashboardView.as_view(), name="owner"),
    path("it-admin/", views.ITAdminDashboardView.as_view(), name="it_admin"),
    path("manager/", views.ManagerDashboardView.as_view(), name="manager"),
    path("cashier/", views.CashierDashboardView.as_view(), name="cashier"),
    path("search/", views.SearchView.as_view(), name="search"),
    path("activity/", views.ActivityView.as_view(), name="activity"),
]
