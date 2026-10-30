from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    # Staff portal
    path("staff/login/", views.StaffLoginView.as_view(), name="staff_login"),
    path("staff/profile/", views.StaffProfileView.as_view(), name="staff_profile"),
    path("staff/users/", views.StaffListView.as_view(), name="staff_list"),
    path("staff/users/new/", views.StaffCreateView.as_view(), name="staff_create"),
    path("staff/users/<int:pk>/", views.StaffDetailView.as_view(), name="staff_detail"),
    path("staff/users/<int:pk>/edit/", views.StaffUpdateView.as_view(), name="staff_update"),
    path("staff/users/<int:pk>/toggle-active/", views.StaffToggleActiveView.as_view(), name="staff_toggle_active"),
    path("staff/users/<int:pk>/set-password/", views.StaffSetPasswordView.as_view(), name="staff_set_password"),

    # Customer portal
    path("account/login/", views.CustomerLoginView.as_view(), name="customer_login"),
    path("account/register/", views.CustomerRegisterView.as_view(), name="register"),
    path("account/", views.CustomerHomeView.as_view(), name="customer_home"),
    path("account/profile/", views.CustomerProfileView.as_view(), name="customer_profile"),

    # Shared
    path("logout/", views.LogoutView.as_view(), name="logout"),
    path("signed-in/", views.LoginRedirectView.as_view(), name="login_redirect"),
    path("password/change/", views.PasswordChangeView.as_view(), name="password_change"),
    path("password/reset/", views.PasswordResetView.as_view(), name="password_reset"),
    path("password/reset/sent/", views.PasswordResetDoneView.as_view(), name="password_reset_done"),
    path("password/reset/<uidb64>/<token>/", views.PasswordResetConfirmView.as_view(), name="password_reset_confirm"),
    path("password/reset/complete/", views.PasswordResetCompleteView.as_view(), name="password_reset_complete"),
]
