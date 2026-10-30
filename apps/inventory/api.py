"""
Inventory API (/api/v1/inventory/...). Staff only: Owner and Manager.

  items/                 MANAGE_INVENTORY   list/create/update settings (quantity is read-only)
  items/<id>/adjust/     MANAGE_INVENTORY   POST a stock adjustment (same rules as the web form)
  movements/             MANAGE_INVENTORY   read-only ledger
  suppliers/             MANAGE_SUPPLIERS
  purchases/             MANAGE_PURCHASES   drafts editable; POST <id>/receive/ and <id>/cancel/

No DELETE anywhere: suppliers and items are deactivated, purchases cancelled.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.permissions import HasCapability
from apps.accounts.roles import Capability, has_capability
from apps.catalog.api import CatalogPagination, ModelCleanMixin
from apps.catalog.models import Unit

from . import services
from .forms import ItemFilterForm, PurchaseFilterForm
from .models import InventoryItem, Purchase, PurchaseLine, StockMovement, Supplier


def as_drf_error(error):
    return serializers.ValidationError(error.message_dict if hasattr(error, "error_dict") else error.messages)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
class InventoryItemSerializer(ModelCleanMixin, serializers.ModelSerializer):
    display_name = serializers.CharField(read_only=True)
    quantity_display = serializers.CharField(read_only=True)
    unit_label = serializers.CharField(read_only=True)
    state = serializers.CharField(read_only=True)
    opening_quantity = serializers.DecimalField(max_digits=14, decimal_places=3, min_value=Decimal("0"),
                                                required=False, write_only=True)

    class Meta:
        model = InventoryItem
        fields = ["id", "kind", "variation", "name", "category", "stock_unit", "count_label", "display_name",
                  "quantity", "quantity_display", "unit_label", "state", "reorder_level", "minimum_level",
                  "maximum_level", "allow_negative", "is_active", "notes", "last_movement_at", "opening_quantity",
                  "created_at", "updated_at"]
        read_only_fields = ["quantity", "last_movement_at", "created_at", "updated_at"]

    def validate(self, attrs):
        if "allow_negative" in attrs and not has_capability(self.context["request"].user, Capability.CONFIGURE_STOCK_RULES):
            if attrs["allow_negative"] != getattr(self.instance, "allow_negative", False):
                raise serializers.ValidationError({"allow_negative": "Only the Owner can change this setting."})
        if self.instance is not None:
            for fixed in ("kind", "variation"):
                if fixed in attrs and attrs[fixed] != getattr(self.instance, fixed):
                    raise serializers.ValidationError({fixed: "Cannot be changed after the item is created."})
        # Opening stock is only accepted when creating; it is not a model field.
        opening = attrs.pop("opening_quantity", None)
        attrs = super().validate(attrs)
        if opening is not None and self.instance is None:
            attrs["opening_quantity"] = opening
        return attrs

    def create(self, validated_data):
        opening = validated_data.pop("opening_quantity", None)
        item = InventoryItem(**validated_data)
        try:
            return services.create_item_with_opening_stock(item, opening, self.context["request"].user)
        except DjangoValidationError as error:
            raise as_drf_error(error)


class StockMovementSerializer(serializers.ModelSerializer):
    item_name = serializers.CharField(source="item.display_name", read_only=True)
    movement_type_display = serializers.CharField(source="get_movement_type_display", read_only=True)
    created_by = serializers.StringRelatedField()

    class Meta:
        model = StockMovement
        fields = ["id", "item", "item_name", "movement_type", "movement_type_display", "quantity_change",
                  "quantity_before", "quantity_after", "entered_quantity", "entered_unit", "reason", "purchase",
                  "created_at", "created_by"]
        read_only_fields = fields


class AdjustmentSerializer(serializers.Serializer):
    movement_type = serializers.ChoiceField(choices=[(t.value, t.label) for t in services.MANUAL_TYPES])
    quantity = serializers.DecimalField(max_digits=14, decimal_places=3, min_value=Decimal("0"))
    unit = serializers.PrimaryKeyRelatedField(queryset=Unit.objects.all(), required=False, allow_null=True)
    direction = serializers.ChoiceField(choices=["in", "out"], required=False)
    reason = serializers.CharField(max_length=500)


class SupplierSerializer(ModelCleanMixin, serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = ["id", "name", "contact_person", "phone", "email", "address", "registration_number", "notes",
                  "is_active", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]


class PurchaseLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = PurchaseLine
        fields = ["id", "item", "quantity", "unit", "unit_cost", "line_total"]
        read_only_fields = ["line_total"]

    def validate(self, attrs):
        line = PurchaseLine(**attrs)
        if line.item.is_finished:
            attrs["unit"] = line.unit = None
        try:
            line.clean()
        except DjangoValidationError as error:
            raise as_drf_error(error)
        return attrs


class PurchaseSerializer(serializers.ModelSerializer):
    lines = PurchaseLineSerializer(many=True)
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)

    class Meta:
        model = Purchase
        fields = ["id", "reference", "supplier", "supplier_name", "purchase_date", "invoice_number", "status",
                  "notes", "subtotal", "total", "lines", "created_at", "received_at", "cancelled_at", "cancel_reason"]
        read_only_fields = ["reference", "status", "subtotal", "total", "created_at", "received_at",
                            "cancelled_at", "cancel_reason"]

    def validate_lines(self, lines):
        if not lines:
            raise serializers.ValidationError("Add at least one item.")
        return lines

    def _write_lines(self, purchase, lines):
        purchase.lines.all().delete()
        for line in lines:
            PurchaseLine.objects.create(purchase=purchase, **line)
        purchase.recalculate_totals()

    @transaction.atomic
    def create(self, validated_data):
        lines = validated_data.pop("lines")
        purchase = services.save_new_purchase(Purchase(**validated_data), self.context["request"].user)
        self._write_lines(purchase, lines)
        return purchase

    @transaction.atomic
    def update(self, instance, validated_data):
        if not Purchase.objects.select_for_update().filter(pk=instance.pk, status=Purchase.Status.DRAFT).exists():
            raise serializers.ValidationError("Only draft purchases can be edited.")
        lines = validated_data.pop("lines", None)
        for key, value in validated_data.items():
            setattr(instance, key, value)
        instance.save()
        if lines is not None:
            self._write_lines(instance, lines)
        return instance


# ---------------------------------------------------------------------------
# ViewSets
# ---------------------------------------------------------------------------
class NoDeleteViewSet(mixins.CreateModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin,
                      mixins.ListModelMixin, viewsets.GenericViewSet):
    permission_classes = [HasCapability]
    pagination_class = CatalogPagination


class InventoryItemViewSet(NoDeleteViewSet):
    queryset = InventoryItem.objects.all()  # type hint for API docs; get_queryset() filters
    required_capability = Capability.MANAGE_INVENTORY
    serializer_class = InventoryItemSerializer

    def get_queryset(self):
        return services.filter_items(ItemFilterForm(self.request.query_params or None).filters())

    @action(detail=True, methods=["post"])
    def adjust(self, request, pk=None):
        item = self.get_object()
        data = AdjustmentSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        d = data.validated_data
        try:
            movement = services.record_movement(item, d["movement_type"], d["quantity"], request.user,
                                                reason=d["reason"], unit=d.get("unit"), direction=d.get("direction"))
        except DjangoValidationError as error:
            raise as_drf_error(error)
        return Response(StockMovementSerializer(movement).data, status=status.HTTP_201_CREATED)


class StockMovementViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [HasCapability]
    required_capability = Capability.MANAGE_INVENTORY
    serializer_class = StockMovementSerializer
    pagination_class = CatalogPagination

    def get_queryset(self):
        qs = StockMovement.objects.select_related("item__variation__product", "item__stock_unit", "created_by")
        item = self.request.query_params.get("item")
        return qs.filter(item_id=item) if item and item.isdigit() else qs


class SupplierViewSet(NoDeleteViewSet):
    required_capability = Capability.MANAGE_SUPPLIERS
    serializer_class = SupplierSerializer
    queryset = Supplier.objects.order_by("name")


class PurchaseViewSet(NoDeleteViewSet):
    queryset = Purchase.objects.all()  # type hint for API docs; get_queryset() filters
    required_capability = Capability.MANAGE_PURCHASES
    serializer_class = PurchaseSerializer

    def get_queryset(self):
        return (services.filter_purchases(PurchaseFilterForm(self.request.query_params or None).filters())
                .prefetch_related("lines"))

    @action(detail=True, methods=["post"])
    def receive(self, request, pk=None):
        try:
            purchase = services.receive_purchase(self.get_object(), request.user)
        except DjangoValidationError as error:
            raise as_drf_error(error)
        return Response(PurchaseSerializer(purchase, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        try:
            purchase = services.cancel_purchase(self.get_object(), request.user, request.data.get("reason", ""))
        except DjangoValidationError as error:
            raise as_drf_error(error)
        return Response(PurchaseSerializer(purchase, context={"request": request}).data)
