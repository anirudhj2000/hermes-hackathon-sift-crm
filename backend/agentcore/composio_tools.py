"""Composio tool bridge for the Sift agent.

Exposes curated Gmail actions — the same actions Composio serves over its
MCP servers — as agent tools, executed against the user's connected account
via Composio v3 `tools/execute`. Schemas are pinned locally so the agent
prompt stays small and startup needs no Composio roundtrip; execution is
always live.
"""

import httpx
from django.conf import settings

COMPOSIO_BASE = "https://backend.composio.dev/api/v3"

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "GMAIL_FETCH_EMAILS",
            "description": (
                "Search the user's connected Gmail account (via Composio). "
                "Use Gmail query syntax, e.g. 'newer_than:7d from:billing@acme.com is:unread'. "
                "Returns sender, subject, date and a text preview per message."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Gmail search query (default: newer_than:7d).",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Max messages to return (default 20, max 50).",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "GMAIL_SEND_EMAIL",
            "description": (
                "Send an email from the user's connected Gmail account (via Composio). "
                "Only use when the user explicitly asks to send an email, and confirm "
                "recipient, subject and body with them first."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "recipient_email": {"type": "string", "description": "To address."},
                    "subject": {"type": "string", "description": "Subject line."},
                    "body": {"type": "string", "description": "Plain-text body."},
                },
                "required": ["recipient_email", "subject", "body"],
            },
        },
    },
]

_TOOL_NAMES = {t["function"]["name"] for t in TOOL_SCHEMAS}


def available():
    return bool(getattr(settings, "COMPOSIO_API_KEY", ""))


def is_composio_tool(name):
    return name in _TOOL_NAMES


def _user_id():
    """The user_id the Gmail OAuth connection was created under."""
    try:
        from crm.models import Connection

        conn = Connection.objects.filter(source="gmail").first()
        return ((conn and conn.meta) or {}).get("user_id") or "sift-demo"
    except Exception:
        return "sift-demo"


def execute(slug, arguments):
    if not available():
        return {"error": "composio not configured — set COMPOSIO_API_KEY and connect gmail"}
    if slug == "GMAIL_FETCH_EMAILS":
        arguments = {
            "query": (arguments or {}).get("query") or "newer_than:7d",
            "max_results": min(int((arguments or {}).get("max_results") or 20), 50),
        }
    resp = httpx.post(
        f"{COMPOSIO_BASE}/tools/execute/{slug}",
        headers={"x-api-key": settings.COMPOSIO_API_KEY, "Content-Type": "application/json"},
        json={"user_id": _user_id(), "arguments": arguments or {}},
        timeout=30.0,
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("successful") is False:
        return {"error": payload.get("error") or "composio execution failed"}
    data = payload.get("data") or {}
    if slug == "GMAIL_FETCH_EMAILS":
        msgs = data.get("messages") or []
        return {
            "count": len(msgs),
            "messages": [
                {
                    "from": m.get("sender", ""),
                    "subject": m.get("subject", ""),
                    "date": m.get("messageTimestamp") or m.get("date", ""),
                    "preview": message_text(m)[:300],
                }
                for m in msgs
            ],
        }
    return data


def message_text(m):
    """Plain-text body from a v3 gmail message: `preview` is {body: str};
    `messageText` is raw HTML — used tag-stripped as the fallback."""
    preview = m.get("preview")
    if isinstance(preview, dict) and preview.get("body"):
        return str(preview["body"])
    if isinstance(preview, str) and preview:
        return preview
    import re

    html = str(m.get("messageText") or "")
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()
