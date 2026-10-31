from django.urls import path

from . import review_views, views

app_name = "shop"

urlpatterns = [
    path("shop/", views.ShopHomeView.as_view(), name="home"),
    path("shop/category/<slug:slug>/", views.CategoryView.as_view(), name="category"),
    path("shop/product/<slug:slug>/", views.ProductDetailView.as_view(), name="product"),
    path("shop/product/<slug:slug>/wishlist/", review_views.WishlistToggleView.as_view(), name="wishlist_toggle"),
    path("shop/product/<slug:slug>/review/", review_views.ReviewFormView.as_view(), name="review"),
    path("account/wishlist/", review_views.WishlistView.as_view(), name="wishlist"),
    path("staff/reviews/", review_views.ReviewModerationView.as_view(), name="review_moderation"),
    path("staff/reviews/<int:pk>/moderate/", review_views.ReviewModerateView.as_view(), name="review_moderate"),
    path("cart/", views.CartView.as_view(), name="cart"),
    path("cart/add/", views.AddToCartView.as_view(), name="cart_add"),
    path("cart/items/<int:pk>/update/", views.UpdateCartItemView.as_view(), name="cart_update"),
    path("cart/items/<int:pk>/remove/", views.RemoveCartItemView.as_view(), name="cart_remove"),
]
