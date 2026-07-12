from django.conf import settings
from django.db.models import Count
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Connection, DataTable, Workflow, WorkflowRun
from .serializers import (
    ConnectionSerializer,
    RecordSerializer,
    TableSerializer,
    WorkflowRunSerializer,
    WorkflowSerializer,
)

RECORDS_MAX = 500


class TableViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = TableSerializer
    lookup_field = "slug"

    def get_queryset(self):
        return DataTable.objects.annotate(record_count=Count("records")).order_by("-created_at")

    @action(detail=True, methods=["get"])
    def records(self, request, slug=None):
        """Newest-first records; ?search= icontains across data values."""
        table = self.get_object()
        rows = list(table.records.order_by("-created_at", "-id")[:RECORDS_MAX])
        search = (request.query_params.get("search") or "").strip().lower()
        if search:
            rows = [
                r
                for r in rows
                if any(
                    search in str(value).lower()
                    for value in (r.data or {}).values()
                    if value is not None
                )
            ]
        return Response(RecordSerializer(rows, many=True).data)


class WorkflowViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    queryset = Workflow.objects.order_by("-created_at")
    serializer_class = WorkflowSerializer

    @action(detail=True, methods=["post"])
    def run(self, request, pk=None):
        workflow = self.get_object()
        try:
            from pipelines.engine import start_run
        except ImportError:
            return Response(
                {"detail": "pipelines engine not available yet"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        run = start_run(workflow)
        return Response({"run_id": run.id}, status=status.HTTP_202_ACCEPTED)


class WorkflowRunViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = WorkflowRun.objects.order_by("-id")
    serializer_class = WorkflowRunSerializer


class ConnectionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Connection.objects.order_by("source")
    serializer_class = ConnectionSerializer

    @action(detail=False, methods=["post"], url_path="whatsapp/pair")
    def whatsapp_pair(self, request):
        conn, _ = Connection.objects.get_or_create(source="whatsapp")
        try:
            import httpx

            resp = httpx.get(f"{settings.SIDECAR_URL}/qr", timeout=5.0)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            # Sidecar unreachable — stay offline-friendly.
            conn.status = "disconnected"
            conn.save(update_fields=["status"])
            return Response({"qr": None, "connected": False})
        connected = bool(data.get("connected"))
        conn.status = "connected" if connected else "pending"
        conn.save(update_fields=["status"])
        return Response({"qr": data.get("qr"), "connected": connected})

    @action(detail=False, methods=["post"], url_path="gmail/connect")
    def gmail_connect(self, request):
        conn, _ = Connection.objects.get_or_create(source="gmail")
        if not settings.COMPOSIO_API_KEY:
            # Mock mode: mark as connected immediately.
            conn.status = "connected"
            conn.meta = {**conn.meta, "mode": "mock"}
            conn.save(update_fields=["status", "meta"])
            return Response({"status": "connected"})
        # Live mode placeholder: integrator wires the real Composio OAuth flow.
        conn.status = "pending"
        conn.save(update_fields=["status"])
        return Response({"status": "pending", "redirect_url": None})
