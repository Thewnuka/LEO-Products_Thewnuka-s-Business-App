from django.urls import path

from . import views

app_name = "shop"

urlpatterns = [
    path("shop/", views.ShopHomeView.as_view(), name="home"),
    path("shop/category/<slug:slug>/", views.CategoryView.as_view(), name="category"),
    path("shop/product/<slug:slug>/", views.ProductDetailView.as_view(), name="product"),
    path("cart/", views.CartView.as_view(), name="cart"),
    path("cart/add/", views.AddToCartView.as_view(), name="cart_add"),
    path("cart/items/<int:pk>/update/", views.UpdateCartItemView.as_view(), name="cart_update"),
    path("cart/items/<int:pk>/remove/", views.RemoveCartItemView.as_view(), name="cart_remove"),
]
