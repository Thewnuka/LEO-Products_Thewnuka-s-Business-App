from rest_framework.routers import SimpleRouter

from . import api

router = SimpleRouter()
router.register("categories", api.CategoryViewSet, basename="catalog-category")
router.register("units", api.UnitViewSet, basename="catalog-unit")
router.register("products", api.ProductViewSet, basename="catalog-product")
router.register("variations", api.VariationViewSet, basename="catalog-variation")

urlpatterns = router.urls
