"""WhatsApp message source (v2 — persistent, scope-first).

Reads from the WaMessage store (populated by the sidecar via
/api/ingest/whatsapp, or by fixture seeding in mock mode) instead of
hitting the sidecar per fetch. Hard gate: only chats the user has
explicitly scoped are visible to workflows — no scoped chats means the
fetch fails with an actionable error.

Supports either a relative window (`since_days`) or an absolute date
range (`from_date` / `to_date`, ISO dates), optionally narrowed to
specific `chat_jids` within the scoped set.
"""

from datetime import datetime, timedelta, timezone

from ..models import WaChat, WaMessage


def _parse_date(value, end_of_day=False):
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if end_of_day and len(str(value)) <= 10:
        dt = dt + timedelta(days=1) - timedelta(microseconds=1)
    return dt


def fetch(since_days=None, from_date=None, to_date=None, chat_jids=None):
    """Return IngestMessage-shaped dicts from scoped chats only."""
    if not WaChat.objects.exists():
        raise ValueError(
            "no WhatsApp chats synced yet — open the WhatsApp page and sync chats first"
        )

    scoped = WaChat.objects.filter(scoped=True)
    if not scoped.exists():
        raise ValueError(
            "no WhatsApp chats are scoped — select chats on the WhatsApp page first"
        )
    if chat_jids:
        scoped = scoped.filter(jid__in=chat_jids)
        if not scoped.exists():
            raise ValueError(
                "none of the requested chat_jids are in the scoped set — "
                "scope them on the WhatsApp page first"
            )

    qs = WaMessage.objects.filter(chat__in=scoped).select_related("chat")
    if since_days:
        qs = qs.filter(ts__gte=datetime.now(timezone.utc) - timedelta(days=since_days))
    if from_date:
        qs = qs.filter(ts__gte=_parse_date(from_date))
    if to_date:
        qs = qs.filter(ts__lte=_parse_date(to_date, end_of_day=True))

    return [
        {
            "external_id": m.external_id,
            "chat_jid": m.chat.jid,
            "chat_name": m.chat.name,
            "is_group": m.chat.is_group,
            "sender_name": m.sender_name,
            "phone": m.phone,
            "body": m.body,
            "ts": m.ts.isoformat(),
            "direction": m.direction,
        }
        for m in qs.order_by("ts")
    ]
