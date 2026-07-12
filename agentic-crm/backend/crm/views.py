from django.conf import settings
from django.db.models import Count, Max, Q
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Connection, Contact, Interaction, Workflow, WorkflowRun
from .serializers import (
    ConnectionSerializer,
    ContactDetailSerializer,
    ContactListSerializer,
    InteractionSerializer,
    WorkflowRunSerializer,
    WorkflowSerializer,
)


class ContactViewSet(viewsets.ReadOnlyModelViewSet):
    def get_queryset(self):
        qs = Contact.objects.annotate(
            interaction_count=Count("interactions"),
            last_ts=Max("interactions__ts"),
        ).order_by("-created_at")
        search = self.request.query_params.get("search")
        if search:
            qs = qs.filter(
                Q(name__icontains=search)
                | Q(email__icontains=search)
                | Q(phone__icontains=search)
                | Q(company__icontains=search)
            )
        return qs

    def get_serializer_class(self):
        if self.action == "retrieve":
            return ContactDetailSerializer
        return ContactListSerializer


class InteractionViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = InteractionSerializer

    def get_queryset(self):
        qs = Interaction.objects.order_by("-ts")
        contact = self.request.query_params.get("contact")
        if contact:
            qs = qs.filter(contact_id=contact)
        return qs


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
