"""Gmail message source (via Composio REST when configured).

If `COMPOSIO_API_KEY` is set, fetches messages through Composio's REST API
using httpx (clean seam; not exercised without a key). Otherwise — or on
any error — reads the bundled fixture file, filtered by `since_days`.
"""

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "gmail.json"

COMPOSIO_BASE_URL = "https://backend.composio.dev/api/v3"


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _parse_date(value, end_of_day=False):
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if end_of_day and len(str(value)) <= 10:
        dt = dt + timedelta(days=1) - timedelta(microseconds=1)
    return dt


def _filter_window(messages, since_days=None, from_date=None, to_date=None):
    lo = None
    hi = None
    if since_days:
        lo = datetime.now(timezone.utc) - timedelta(days=since_days)
    if from_date:
        lo = _parse_date(from_date)
    if to_date:
        hi = _parse_date(to_date, end_of_day=True)
    kept = []
    for msg in messages:
        try:
            ts = _parse_ts(msg["ts"])
        except (KeyError, ValueError):
            continue
        if lo is not None and ts < lo:
            continue
        if hi is not None and ts > hi:
            continue
        kept.append(msg)
    return kept


def _load_fixture(since_days=None, from_date=None, to_date=None):
    with open(FIXTURE_PATH) as f:
        return _filter_window(json.load(f), since_days, from_date, to_date)


def _composio_user_id():
    """The user_id the OAuth connection was created under (crm connect flow)."""
    try:
        from crm.models import Connection

        conn = Connection.objects.filter(source="gmail").first()
        return ((conn and conn.meta) or {}).get("user_id") or "sift-demo"
    except Exception:
        return "sift-demo"


def _split_sender(sender):
    """'Name <a@b.c>' → (Name, a@b.c); plain address → (address, address)."""
    m = re.match(r"^\s*\"?(.*?)\"?\s*<([^>]+)>\s*$", sender or "")
    if m:
        return (m.group(1) or m.group(2), m.group(2))
    return (sender or "", sender or "")


def _fetch_via_composio(api_key, since_days=None, from_date=None, to_date=None) -> list[dict]:
    """Fetch recent Gmail messages through Composio's v3 REST API and map
    them to the gmail fixture shape. Requires an ACTIVE connected account."""
    if from_date or to_date:
        parts = []
        if from_date:
            parts.append(f"after:{str(from_date)[:10].replace('-', '/')}")
        if to_date:
            hi = _parse_date(to_date, end_of_day=True) + timedelta(days=1)
            parts.append(f"before:{hi.strftime('%Y/%m/%d')}")
        query = " ".join(parts)
    else:
        query = f"newer_than:{since_days or 7}d"
    resp = httpx.post(
        f"{COMPOSIO_BASE_URL}/tools/execute/GMAIL_FETCH_EMAILS",
        headers={"x-api-key": api_key, "Content-Type": "application/json"},
        json={
            "user_id": _composio_user_id(),
            "arguments": {"query": query, "max_results": 100},
        },
        timeout=30.0,
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("successful") is False:
        raise RuntimeError(payload.get("error") or "composio execute failed")
    raw = (payload.get("data") or {}).get("messages") or []
    messages = []
    for item in raw:
        from agentcore.composio_tools import message_text

        sender_name, sender_email = _split_sender(item.get("sender", ""))
        messages.append(
            {
                "external_id": f"gm-{item.get('messageId') or item.get('id')}",
                "sender_name": item.get("senderName") or sender_name,
                "email": item.get("senderEmail") or sender_email,
                "subject": item.get("subject", ""),
                "body": message_text(item),
                "ts": item.get("messageTimestamp") or item.get("date", ""),
                "direction": "in",
            }
        )
    return _filter_window(messages, since_days, from_date, to_date)


def fetch(since_days=None, from_date=None, to_date=None, **_ignored) -> list[dict]:
    """Return gmail message dicts from the window (relative or absolute)."""
    import os

    api_key = getattr(settings, "COMPOSIO_API_KEY", "")
    if api_key:
        try:
            return _fetch_via_composio(api_key, since_days, from_date, to_date)
        except Exception as exc:
            # Fixture fallback is opt-in — real runs must fail loudly rather
            # than silently filling tables with demo emails.
            if os.environ.get("SIFT_MOCK_FALLBACK") != "1":
                raise
            logger.warning("composio gmail fetch failed (%s) — using fixture", exc)
    elif os.environ.get("SIFT_MOCK_FALLBACK") != "1":
        raise RuntimeError("gmail not configured — set COMPOSIO_API_KEY and connect gmail")
    return _load_fixture(since_days, from_date, to_date)
