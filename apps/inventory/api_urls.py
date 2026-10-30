from rest_framework.routers import SimpleRouter

from . import api

router = SimpleRouter()
router.register("items", api.InventoryItemViewSet, basename="inventory-item")
router.register("movements", api.StockMovementViewSet, basename="inventory-movement")
router.register("suppliers", api.SupplierViewSet, basename="inventory-supplier")
router.register("purchases", api.PurchaseViewSet, basename="inventory-purchase")

urlpatterns = router.urls
