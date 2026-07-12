"""WhatsApp message source.

Tries the Baileys sidecar (`POST {SIDECAR_URL}/fetch-history`) with a short
timeout; on any error falls back to the bundled fixture file, filtered by
`since_days`.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from django.conf import settings

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "whatsapp.json"


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _filter_since(messages, since_days):
    cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
    kept = []
    for msg in messages:
        try:
            if _parse_ts(msg["ts"]) >= cutoff:
                kept.append(msg)
        except (KeyError, ValueError):
            continue
    return kept


def _load_fixture(since_days):
    with open(FIXTURE_PATH) as f:
        return _filter_since(json.load(f), since_days)


def fetch(since_days: int) -> list[dict]:
    """Return a list of IngestMessage dicts from the last `since_days` days."""
    sidecar_url = getattr(settings, "SIDECAR_URL", "http://localhost:3001")
    try:
        resp = httpx.post(
            f"{sidecar_url.rstrip('/')}/fetch-history",
            json={"since_days": since_days},
            timeout=2.0,
        )
        resp.raise_for_status()
        data = resp.json()
        messages = data.get("messages", data) if isinstance(data, dict) else data
        if not isinstance(messages, list):
            raise ValueError("unexpected sidecar response shape")
        return _filter_since(messages, since_days)
    except Exception:
        return _load_fixture(since_days)
