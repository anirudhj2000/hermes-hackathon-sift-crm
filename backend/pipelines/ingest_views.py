"""Ingest endpoint: sidecar pushes WhatsApp messages here.

POST /api/ingest/whatsapp
  header  X-Ingest-Secret: <INGEST_SECRET>   (403 on mismatch)
  body    {"messages": [IngestMessage]}
  reply   {"created": int, "skipped": int}

v2: messages land in the persistent WaChat/WaMessage store (groups
included — the sidecar no longer filters them out). Table Records are
NOT created here; workflows sift rows out of *scoped* chats only.
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

            # Display names must never be jids ("...@s.whatsapp.net"); a real
            # name may later replace a placeholder, never the other way round.
            def _clean(value):
                value = (value or "").strip()
                return "" if "@" in value else value

            # A DM's display name is the counterparty, not whoever sent this
            # particular message ("Me" for outbound).
            fallback_name = (
                "" if msg.get("direction") == "out" else _clean(msg.get("sender_name"))
            )
            incoming_name = _clean(msg.get("chat_name")) or fallback_name
            chat, _ = WaChat.objects.get_or_create(
                jid=chat_jid,
                defaults={"name": incoming_name, "is_group": is_group},
            )
            update_fields = []
            sidecar_name = _clean(msg.get("chat_name"))
            placeholder = not chat.name or "@" in chat.name
            if sidecar_name and chat.name != sidecar_name:
                chat.name = sidecar_name  # sidecar meta (subject/contact) wins
                update_fields.append("name")
            elif placeholder and chat.name != (fallback_name or ""):
                chat.name = fallback_name or ""  # upgrade or blank a jid name
                update_fields.append("name")
            if is_group and not chat.is_group:
                chat.is_group = True
                update_fields.append("is_group")
            if update_fields:
                chat.save(update_fields=update_fields)
            chats[chat_jid] = chat

        # Live events (post-pairing) mark the chat as active — only these
        # chats appear in the UI directory; history-only chats stay hidden.
        if msg.get("live") and not (chat.meta or {}).get("live_seen"):
            chat.meta = {**(chat.meta or {}), "live_seen": True}
            chat.save(update_fields=["meta"])

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
