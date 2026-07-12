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
from agentcore.connector_state import refresh as refresh_connector_state

RECORDS_MAX = 500

COMPOSIO_BASE = "https://backend.composio.dev/api/v3"
COMPOSIO_USER_ID = "sift-demo"


def _refresh_pending_gmail():
    """If a hosted-OAuth session was started, poll Composio once so the
    connection flips to connected after the user finishes in Google."""
    if not settings.COMPOSIO_API_KEY:
        return
    conn = Connection.objects.filter(source="gmail", status="pending").first()
    account_id = conn and (conn.meta or {}).get("connected_account_id")
    if not account_id:
        return
    try:
        import httpx

        resp = httpx.get(
            f"{COMPOSIO_BASE}/connected_accounts/{account_id}",
            headers={"x-api-key": settings.COMPOSIO_API_KEY},
            timeout=5.0,
        )
        if resp.status_code == 200 and resp.json().get("status") == "ACTIVE":
            conn.status = "connected"
            conn.meta = {**conn.meta, "mode": "live"}
            conn.save(update_fields=["status", "meta"])
            refresh_connector_state("gmail")
    except Exception:
        pass


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

    @action(detail=True, methods=["patch"], url_path=r"records/(?P<record_id>[0-9]+)")
    def update_record(self, request, slug=None, record_id=None):
        """Merge edited cell values into record.data; values are coerced to
        their column types, unknown columns rejected."""
        from pipelines.extractor import coerce_value

        table = self.get_object()
        record = table.records.filter(id=record_id).first()
        if record is None:
            return Response({"detail": "record not found"}, status=status.HTTP_404_NOT_FOUND)
        patch = request.data.get("data")
        if not isinstance(patch, dict) or not patch:
            return Response(
                {"detail": "body must be {data: {column: value, ...}}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        cols = {c["name"]: c for c in (table.columns or []) if isinstance(c, dict)}
        unknown = [k for k in patch if k not in cols]
        if unknown:
            return Response(
                {"detail": f"unknown columns: {', '.join(unknown)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        merged = dict(record.data or {})
        for key, value in patch.items():
            coerced = coerce_value(value, cols[key])
            if coerced is None and value not in (None, ""):
                ctype = cols[key].get("type", "text")
                if ctype != "text":
                    return Response(
                        {"detail": f"invalid {ctype} value for '{key}'"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
            merged[key] = coerced
        record.data = merged
        record.save(update_fields=["data", "updated_at"])
        return Response(RecordSerializer(record).data)


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

    def list(self, request, *args, **kwargs):
        _refresh_pending_gmail()
        return super().list(request, *args, **kwargs)

    @action(detail=False, methods=["post"], url_path="whatsapp/pair")
    def whatsapp_pair(self, request):
        conn, _ = Connection.objects.get_or_create(source="whatsapp")
        phone = str((request.data or {}).get("phone") or "").strip()
        try:
            import httpx

            if phone:
                # Baileys pairing-code flow: user types the code into
                # WhatsApp → Linked Devices → "Link with phone number".
                resp = httpx.get(
                    f"{settings.SIDECAR_URL}/pair-code",
                    params={"phone": phone},
                    timeout=20.0,
                )
            else:
                resp = httpx.get(f"{settings.SIDECAR_URL}/qr", timeout=5.0)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            # Sidecar unreachable — stay offline-friendly.
            conn.status = "disconnected"
            conn.save(update_fields=["status"])
            return Response({"qr": None, "code": None, "connected": False})
        connected = bool(data.get("connected"))
        conn.status = "connected" if connected else "pending"
        conn.save(update_fields=["status"])
        refresh_connector_state("whatsapp")
        return Response(
            {"qr": data.get("qr"), "code": data.get("code"), "connected": connected}
        )

    @action(
        detail=False,
        methods=["post"],
        url_path=r"(?P<source>whatsapp|gmail)/disconnect",
    )
    def disconnect(self, request, source=None):
        conn, _ = Connection.objects.get_or_create(source=source)
        try:
            import httpx

            if source == "whatsapp":
                # Unlinks the device; the sidecar self-heals into a fresh
                # pairing session so QR/codes are immediately available.
                httpx.post(f"{settings.SIDECAR_URL}/disconnect", timeout=10.0)
            elif settings.COMPOSIO_API_KEY:
                account_id = (conn.meta or {}).get("connected_account_id")
                if account_id:
                    httpx.delete(
                        f"{COMPOSIO_BASE}/connected_accounts/{account_id}",
                        headers={"x-api-key": settings.COMPOSIO_API_KEY},
                        timeout=10.0,
                    )
        except Exception:
            pass  # best-effort upstream cleanup; local state resets regardless
        conn.status = "disconnected"
        conn.meta = {}
        conn.save(update_fields=["status", "meta"])
        refresh_connector_state(source)
        return Response({"status": "disconnected"})

    @action(detail=False, methods=["post"], url_path="gmail/connect")
    def gmail_connect(self, request):
        conn, _ = Connection.objects.get_or_create(source="gmail")
        if not settings.COMPOSIO_API_KEY:
            # Mock mode: mark as connected immediately.
            conn.status = "connected"
            conn.meta = {**conn.meta, "mode": "mock"}
            conn.save(update_fields=["status", "meta"])
            return Response({"status": "connected"})
        # Live mode: Composio v3 hosted OAuth. The UI opens redirect_url in a
        # new tab; _refresh_pending_gmail flips the status once Google is done.
        headers = {"x-api-key": settings.COMPOSIO_API_KEY}
        meta = conn.meta or {}
        try:
            import httpx

            account_id = meta.get("connected_account_id")
            if account_id:
                resp = httpx.get(
                    f"{COMPOSIO_BASE}/connected_accounts/{account_id}",
                    headers=headers,
                    timeout=10.0,
                )
                if resp.status_code == 200 and resp.json().get("status") == "ACTIVE":
                    conn.status = "connected"
                    conn.meta = {**meta, "mode": "live"}
                    conn.save(update_fields=["status", "meta"])
                    refresh_connector_state("gmail")
                    return Response({"status": "connected"})

            auth_config_id = meta.get("auth_config_id")
            if not auth_config_id:
                resp = httpx.get(
                    f"{COMPOSIO_BASE}/auth_configs",
                    params={"toolkit_slug": "gmail"},
                    headers=headers,
                    timeout=10.0,
                )
                resp.raise_for_status()
                items = resp.json().get("items") or []
                if items:
                    auth_config_id = items[0]["id"]
                else:
                    resp = httpx.post(
                        f"{COMPOSIO_BASE}/auth_configs",
                        headers=headers,
                        json={
                            "toolkit": {"slug": "gmail"},
                            "auth_config": {"type": "use_composio_managed_auth"},
                        },
                        timeout=15.0,
                    )
                    resp.raise_for_status()
                    payload = resp.json()
                    auth_config_id = (payload.get("auth_config") or payload)["id"]

            resp = httpx.post(
                f"{COMPOSIO_BASE}/connected_accounts",
                headers=headers,
                json={
                    "auth_config": {"id": auth_config_id},
                    "connection": {"user_id": COMPOSIO_USER_ID},
                },
                timeout=15.0,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            conn.status = "disconnected"
            conn.save(update_fields=["status"])
            return Response({"status": "disconnected", "redirect_url": None})
        conn.status = "pending"
        conn.meta = {
            **meta,
            "mode": "live",
            "auth_config_id": auth_config_id,
            "connected_account_id": data.get("id"),
            "user_id": COMPOSIO_USER_ID,
        }
        conn.save(update_fields=["status", "meta"])
        refresh_connector_state("gmail")
        return Response({"status": "pending", "redirect_url": data.get("redirect_url")})
