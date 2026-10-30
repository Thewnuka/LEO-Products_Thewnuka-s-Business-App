from django.conf import settings
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView


class HealthCheckSerializer(serializers.Serializer):
    status = serializers.CharField()
    app = serializers.CharField()
    version = serializers.CharField()


class HealthCheckView(APIView):
    """
    Lightweight "is the backend reachable?" endpoint.

    The future desktop (Tauri) and PWA clients can call this before
    syncing. It reveals no private data.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(summary="Backend health check", responses=HealthCheckSerializer)
    def get(self, request):
        return Response(
            {
                "status": "ok",
                "app": settings.BRAND["NAME"],
                "version": settings.APP_VERSION,
            }
        )
