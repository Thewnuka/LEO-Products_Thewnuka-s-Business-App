"""
Catalogue API (/api/v1/catalog/...), for future staff tools (desktop app, PWA).

All endpoints require Capability.MANAGE_CATALOG (OWNER, MANAGER). There is no
public catalogue API yet; the customer storefront arrives in a later phase.
DELETE is not offered: archive records by setting is_active / status instead.
"""
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers, viewsets
from rest_framework.pagination import PageNumberPagination

from apps.accounts.permissions import HasCapability
from apps.accounts.roles import Capability

from .forms import ProductFilterForm
from .images import process_image
from .models import Category, Product, ProductVariation, Unit
from .services import filter_products


class ModelCleanMixin:
    """Runs the model's clean() so the API enforces the same rules as the web forms."""

    def validate(self, attrs):
        attrs = super().validate(attrs)
        instance = self.instance or self.Meta.model()
        for key, value in attrs.items():
            setattr(instance, key, value)
        try:
            instance.clean()
        except DjangoValidationError as error:
            raise serializers.ValidationError(error.message_dict if hasattr(error, "error_dict") else error.messages)
        return attrs

    def validate_image(self, value):
        if value and hasattr(value, "content_type"):
            try:
                return process_image(value)
            except DjangoValidationError as error:
                raise serializers.ValidationError(error.messages)
        return value


class CategorySerializer(ModelCleanMixin, serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "parent", "name", "slug", "description", "image", "is_active", "sort_order", "created_at", "updated_at"]
        read_only_fields = ["slug", "created_at", "updated_at"]


class UnitSerializer(ModelCleanMixin, serializers.ModelSerializer):
    class Meta:
        model = Unit
        fields = ["id", "measurement_type", "name", "symbol", "attach_symbol", "is_active", "sort_order"]


class VariationSerializer(ModelCleanMixin, serializers.ModelSerializer):
    size_label = serializers.CharField(read_only=True)

    class Meta:
        model = ProductVariation
        fields = ["id", "product", "name", "measurement_type", "quantity", "unit", "size_label", "sku",
                  "selling_price", "wholesale_price", "is_active", "image", "sort_order", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]
        extra_kwargs = {"sku": {"required": False, "allow_blank": True, "validators": []}}

    def validate_sku(self, value):
        sku = (value or "").strip().upper()
        qs = ProductVariation.objects.filter(sku__iexact=sku)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if sku and qs.exists():
            raise serializers.ValidationError("This SKU is already used by another variation.")
        return sku

    def validate(self, attrs):
        attrs = super().validate(attrs)
        get = lambda k: attrs.get(k, getattr(self.instance, k, None))  # noqa: E731
        product, unit, quantity = get("product"), get("unit"), get("quantity")
        if product and unit and quantity:
            clash = ProductVariation.objects.filter(product=product, unit=unit, quantity=quantity)
            if self.instance:
                clash = clash.exclude(pk=self.instance.pk)
            if clash.exists():
                raise serializers.ValidationError({"quantity": "This product already has a variation of this size."})
        selling, wholesale = get("selling_price"), get("wholesale_price")
        if selling and wholesale and wholesale > selling:
            raise serializers.ValidationError({"wholesale_price": "Wholesale price cannot be higher than the selling price."})
        return attrs


class ProductSerializer(ModelCleanMixin, serializers.ModelSerializer):
    variations = VariationSerializer(many=True, read_only=True)

    class Meta:
        model = Product
        fields = ["id", "name", "slug", "description", "category", "subcategory", "image", "status",
                  "variations", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]
        extra_kwargs = {"slug": {"required": False}}


class CatalogPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class CatalogViewSet(viewsets.ModelViewSet):
    permission_classes = [HasCapability]
    required_capability = Capability.MANAGE_CATALOG
    pagination_class = CatalogPagination
    http_method_names = ["get", "post", "put", "patch", "head", "options"]  # no DELETE


class CategoryViewSet(CatalogViewSet):
    queryset = Category.objects.select_related("parent")
    serializer_class = CategorySerializer


class UnitViewSet(CatalogViewSet):
    queryset = Unit.objects.all()
    serializer_class = UnitSerializer


class ProductViewSet(CatalogViewSet):
    serializer_class = ProductSerializer

    def get_queryset(self):
        """Supports ?q=, category, subcategory, status, measurement, sort (same as the web list)."""
        filters = ProductFilterForm(self.request.query_params or None).filters()
        return filter_products(filters).prefetch_related("variations__unit")

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, updated_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)


class VariationViewSet(CatalogViewSet):
    serializer_class = VariationSerializer

    def get_queryset(self):
        qs = ProductVariation.objects.select_related("product", "unit").order_by("product__name", "sort_order", "quantity")
        product = self.request.query_params.get("product")
        return qs.filter(product_id=product) if product and product.isdigit() else qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, updated_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)
