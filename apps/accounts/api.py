from rest_framework import generics, serializers
from rest_framework.permissions import IsAuthenticated

from .models import User, identifier_taken


class MeSerializer(serializers.ModelSerializer):
    """The signed-in user's own account. Password fields are never included."""

    role_display = serializers.CharField(source="get_role_display", read_only=True)

    class Meta:
        model = User
        fields = ["id", "username", "email", "first_name", "last_name", "phone_number", "role", "role_display"]
        read_only_fields = ["id", "username", "role", "role_display"]

    def validate_email(self, value):
        value = value.strip().lower()
        if not value:
            raise serializers.ValidationError("Email is required.")
        if identifier_taken(value, exclude_pk=self.instance.pk):
            raise serializers.ValidationError("Another account already uses this email address.")
        return value


class MeView(generics.RetrieveUpdateAPIView):
    """GET / PATCH the signed-in user's own profile. Role cannot be changed here."""

    serializer_class = MeSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "patch", "options"]

    def get_object(self):
        return self.request.user
