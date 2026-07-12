"""Ingest endpoint: sidecar pushes WhatsApp messages here (see CONTRACTS.md).

POST /api/ingest/whatsapp
  header  X-Ingest-Secret: <INGEST_SECRET>   (403 on mismatch)
  body    {"messages": [IngestMessage]}
  reply   {"created": int, "skipped": int}   dedupe on (source, external_id)
"""

import json
from datetime import datetime, timezone as dt_timezone

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from crm.models import Contact, Interaction

from .extractor import normalize_phone


def _parse_ts(value):
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=dt_timezone.utc)
    return dt


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

    created_count = 0
    skipped_count = 0
    for msg in raw_messages:
        external_id = msg.get("external_id")
        if not external_id:
            skipped_count += 1
            continue
        try:
            ts = _parse_ts(msg.get("ts"))
        except (TypeError, ValueError):
            skipped_count += 1
            continue

        # Link to an existing contact by phone if we have one.
        contact = None
        phone = normalize_phone(msg.get("phone"))
        if phone:
            contact = Contact.objects.filter(phone=phone).first()

        _, created = Interaction.objects.get_or_create(
            source="whatsapp",
            external_id=external_id,
            defaults={
                "contact": contact,
                "direction": msg.get("direction", "in"),
                "body": msg.get("body", ""),
                "ts": ts,
                "extracted": {},
            },
        )
        if created:
            created_count += 1
        else:
            skipped_count += 1

    return JsonResponse({"created": created_count, "skipped": skipped_count})
