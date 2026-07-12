"""Gmail message source (via Composio REST when configured).

If `COMPOSIO_API_KEY` is set, fetches messages through Composio's REST API
using httpx (clean seam; not exercised without a key). Otherwise — or on
any error — reads the bundled fixture file, filtered by `since_days`.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from django.conf import settings

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "gmail.json"

COMPOSIO_BASE_URL = "https://backend.composio.dev/api/v2"


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


def _fetch_via_composio(api_key: str, since_days: int) -> list[dict]:
    """Fetch recent Gmail messages through Composio's REST API and map them
    to the gmail fixture shape. Seam only — requires a real COMPOSIO_API_KEY."""
    resp = httpx.post(
        f"{COMPOSIO_BASE_URL}/actions/GMAIL_FETCH_EMAILS/execute",
        headers={"x-api-key": api_key, "Content-Type": "application/json"},
        json={
            "input": {
                "query": f"newer_than:{since_days}d",
                "max_results": 100,
            }
        },
        timeout=15.0,
    )
    resp.raise_for_status()
    payload = resp.json()
    raw = (payload.get("response_data") or payload.get("data") or {}).get("messages", [])
    messages = []
    for item in raw:
        messages.append(
            {
                "external_id": f"gm-{item.get('messageId') or item.get('id')}",
                "sender_name": item.get("senderName") or item.get("sender", ""),
                "email": item.get("senderEmail") or item.get("sender", ""),
                "subject": item.get("subject", ""),
                "body": item.get("messageText") or item.get("snippet", ""),
                "ts": item.get("messageTimestamp") or item.get("date", ""),
                "direction": "in",
            }
        )
    return _filter_since(messages, since_days)


def fetch(since_days: int) -> list[dict]:
    """Return a list of gmail message dicts from the last `since_days` days."""
    api_key = getattr(settings, "COMPOSIO_API_KEY", "")
    if api_key:
        try:
            return _fetch_via_composio(api_key, since_days)
        except Exception:
            pass
    return _load_fixture(since_days)
