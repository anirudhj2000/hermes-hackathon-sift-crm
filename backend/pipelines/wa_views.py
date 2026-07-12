"""WhatsApp chat management API (v2 — scope-first).

- GET  /api/whatsapp/chats/            list chats/groups with scope flags
- POST /api/whatsapp/chats/sync/       pull chat list from sidecar (fixture
                                       fallback in mock mode, which also seeds
                                       fixture messages so the demo works offline)
- POST /api/whatsapp/chats/<id>/scope/ body {"scoped": bool}
- GET  /api/whatsapp/messages/?chat=<id>&from=YYYY-MM-DD&to=YYYY-MM-DD
                                       date-range browse; scoped chats only
"""

import json
from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path

import httpx
from django.conf import settings
from django.db.models import Count
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .ingest_views import store_messages
from .models import WaChat, WaMessage

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _chat_dict(chat, message_count=None):
    return {
        "id": chat.id,
        "jid": chat.jid,
        "name": chat.name or chat.jid.split("@")[0],
        "is_group": chat.is_group,
        "scoped": chat.scoped,
        "message_count": (
            message_count if message_count is not None else chat.messages.count()
        ),
        "last_message_at": chat.last_message_at.isoformat() if chat.last_message_at else None,
    }


@require_GET
def list_chats(request):
    from django.db.models import Q

    # Directory shows only chats with live (post-pairing) events, plus
    # anything already scoped. History-only chats stay hidden; pass ?all=1
    # to inspect everything.
    chats = WaChat.objects.annotate(n_messages=Count("messages"))
    if request.GET.get("all") != "1":
        chats = chats.filter(Q(scoped=True) | Q(meta__live_seen=True))
    chats = chats.order_by("-scoped", "-last_message_at")
    # Bare list — the frontend consumes an array (or DRF-style {results: []}).
    return JsonResponse(
        [_chat_dict(c, message_count=c.n_messages) for c in chats], safe=False
    )


def _sync_from_sidecar():
    """Pull the live chat list from the sidecar. Raises on any failure."""
    resp = httpx.get(f"{settings.SIDECAR_URL.rstrip('/')}/chats", timeout=5.0)
    resp.raise_for_status()
    chats = resp.json().get("chats", [])
    synced = 0
    for item in chats:
        jid = item.get("jid")
        if not jid:
            continue
        chat, created = WaChat.objects.get_or_create(
            jid=jid,
            defaults={
                "name": item.get("name") or "",
                "is_group": bool(item.get("is_group")) or jid.endswith("@g.us"),
            },
        )
        if not created and item.get("name") and chat.name != item["name"]:
            chat.name = item["name"]
            chat.save(update_fields=["name"])
        synced += 1
    return synced


def _sync_from_fixtures():
    """Mock mode: seed chats and their messages from the bundled fixtures."""
    with open(FIXTURES_DIR / "whatsapp_chats.json") as f:
        chats = json.load(f)
    for item in chats:
        chat, created = WaChat.objects.get_or_create(
            jid=item["jid"],
            defaults={
                "name": item.get("name") or "",
                "is_group": bool(item.get("is_group")),
            },
        )
        if not created and item.get("name") and not chat.name:
            chat.name = item["name"]
            chat.save(update_fields=["name"])
    with open(FIXTURES_DIR / "whatsapp.json") as f:
        store_messages(json.load(f))
    return len(chats)


@csrf_exempt
@require_POST
def sync_chats(request):
    import os

    try:
        synced = _sync_from_sidecar()
        mode = "live"
    except Exception:
        # Fixture fallback is opt-in (SIFT_MOCK_FALLBACK=1) — real deployments
        # must never silently seed demo chats.
        if os.environ.get("SIFT_MOCK_FALLBACK") == "1":
            synced = _sync_from_fixtures()
            mode = "mock"
        else:
            synced = 0
            mode = "offline"

    # Record when the WhatsApp layer first came online so the UI can show
    # "messages available since <date>".
    try:
        from crm.models import Connection

        conn, _ = Connection.objects.get_or_create(source="whatsapp")
        meta = dict(conn.meta or {})
        meta.setdefault("synced_at", datetime.now(dt_timezone.utc).isoformat())
        meta["mode"] = mode
        conn.meta = meta
        conn.save(update_fields=["meta"])
    except Exception:
        pass  # bookkeeping only

    from agentcore.connector_state import refresh as refresh_connector_state

    refresh_connector_state("whatsapp")
    return JsonResponse({"synced": synced, "mode": mode})


@csrf_exempt
@require_POST
def scope_chat(request, pk):
    try:
        chat = WaChat.objects.get(pk=pk)
    except WaChat.DoesNotExist:
        return JsonResponse({"detail": "chat not found"}, status=404)
    try:
        payload = json.loads(request.body or b"{}")
        scoped = bool(payload.get("scoped"))
    except json.JSONDecodeError:
        return JsonResponse({"detail": "invalid JSON body"}, status=400)
    chat.scoped = scoped
    chat.save(update_fields=["scoped"])
    from agentcore.connector_state import refresh as refresh_connector_state

    refresh_connector_state("whatsapp")
    return JsonResponse(_chat_dict(chat))


def _parse_date(value, end_of_day=False):
    """Parse YYYY-MM-DD (or full ISO) to an aware datetime, or None."""
    if not value:
        return None
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=dt_timezone.utc)
    if end_of_day and len(str(value)) <= 10:  # date-only: include the whole day
        dt = dt + timedelta(days=1) - timedelta(microseconds=1)
    return dt


@require_GET
def list_messages(request):
    chat_id = request.GET.get("chat")
    if not chat_id:
        return JsonResponse({"detail": "'chat' query param is required"}, status=400)
    try:
        chat = WaChat.objects.get(pk=chat_id)
    except (WaChat.DoesNotExist, ValueError):
        return JsonResponse({"detail": "chat not found"}, status=404)
    if not chat.scoped:
        return JsonResponse(
            {"detail": "chat is not scoped — enable it on the WhatsApp page first"},
            status=403,
        )

    qs = WaMessage.objects.filter(chat=chat)
    try:
        date_from = _parse_date(request.GET.get("from"))
        date_to = _parse_date(request.GET.get("to"), end_of_day=True)
    except ValueError:
        return JsonResponse({"detail": "invalid date; use YYYY-MM-DD"}, status=400)
    if date_from:
        qs = qs.filter(ts__gte=date_from)
    if date_to:
        qs = qs.filter(ts__lte=date_to)

    try:
        limit = min(int(request.GET.get("limit", 200)), 500)
    except ValueError:
        limit = 200

    total = qs.count()
    messages = [
        {
            "external_id": m.external_id,
            "sender_name": m.sender_name,
            "phone": m.phone,
            "direction": m.direction,
            "body": m.body,
            "ts": m.ts.isoformat(),
        }
        for m in qs.order_by("-ts")[:limit]
    ]
    messages.reverse()  # oldest first for transcript display
    return JsonResponse({"chat": _chat_dict(chat), "count": total, "messages": messages})
