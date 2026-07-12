"""Ingest endpoint: sidecar pushes WhatsApp messages here.

POST /api/ingest/whatsapp
  header  X-Ingest-Secret: <INGEST_SECRET>   (403 on mismatch)
  body    {"messages": [IngestMessage]}
  reply   {"created": int, "skipped": int}

v2: messages land in the persistent WaChat/WaMessage store (groups
included — the sidecar no longer filters them out). CRM Interactions are
NOT created here; workflows create them from *scoped* chats only.
"""

import json
from datetime import datetime, timezone as dt_timezone

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .extractor import normalize_phone
from .models import WaChat, WaMessage


def _parse_ts(value):
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=dt_timezone.utc)
    return dt


def store_messages(raw_messages):
    """Upsert IngestMessage dicts into WaChat/WaMessage. Returns (created, skipped)."""
    created_count = 0
    skipped_count = 0
    chats = {}  # jid -> WaChat, cached per call

    for msg in raw_messages:
        external_id = msg.get("external_id")
        chat_jid = msg.get("chat_jid") or ""
        if not external_id or not chat_jid:
            skipped_count += 1
            continue
        try:
            ts = _parse_ts(msg.get("ts"))
        except (TypeError, ValueError):
            skipped_count += 1
            continue

        chat = chats.get(chat_jid)
        if chat is None:
            is_group = bool(msg.get("is_group")) or chat_jid.endswith("@g.us")
            # A DM's display name is the counterparty, not whoever sent this
            # particular message ("Me" for outbound).
            fallback_name = "" if msg.get("direction") == "out" else (msg.get("sender_name") or "")
            chat, _ = WaChat.objects.get_or_create(
                jid=chat_jid,
                defaults={"name": msg.get("chat_name") or fallback_name, "is_group": is_group},
            )
            update_fields = []
            if msg.get("chat_name") and chat.name != msg["chat_name"]:
                chat.name = msg["chat_name"]
                update_fields.append("name")
            if not chat.name and fallback_name:
                chat.name = fallback_name
                update_fields.append("name")
            if is_group and not chat.is_group:
                chat.is_group = True
                update_fields.append("is_group")
            if update_fields:
                chat.save(update_fields=update_fields)
            chats[chat_jid] = chat

        _, created = WaMessage.objects.get_or_create(
            chat=chat,
            external_id=external_id,
            defaults={
                "sender_jid": msg.get("sender_jid") or "",
                "sender_name": msg.get("sender_name") or "",
                "phone": normalize_phone(msg.get("phone")),
                "direction": msg.get("direction", "in"),
                "body": msg.get("body", ""),
                "ts": ts,
            },
        )
        if created:
            created_count += 1
            if chat.last_message_at is None or ts > chat.last_message_at:
                chat.last_message_at = ts
                chat.save(update_fields=["last_message_at"])
        else:
            skipped_count += 1

    return created_count, skipped_count


@csrf_exempt
@require_POST
def ingest_whatsapp(request):
    secret = request.headers.get("X-Ingest-Secret", "")
    if secret != settings.INGEST_SECRET:
        return JsonResponse({"detail": "invalid ingest secret"}, status=403)

    try:
        payload = json.loads(request.body or b"{}")
        raw_messages = payload.get("messages", [])
        if not isinstance(raw_messages, list):
            raise ValueError("'messages' must be a list")
    except (json.JSONDecodeError, ValueError) as exc:
        return JsonResponse({"detail": f"bad request: {exc}"}, status=400)

    created_count, skipped_count = store_messages(raw_messages)
    return JsonResponse({"created": created_count, "skipped": skipped_count})
