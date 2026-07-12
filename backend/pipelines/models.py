"""Persistent WhatsApp message store (v2 — see pl-wa-mcp pattern).

The sidecar is a stateless bridge; durable state lives here in Postgres:
- WaChat: every chat/group seen on the paired account, with a `scoped`
  flag. Only scoped chats are visible to agent tools and workflow fetches.
- WaMessage: every message (history-synced or live-forwarded), indexed by
  timestamp so the CRM can query arbitrary date ranges.
"""

from django.db import models


class WaChat(models.Model):
    jid = models.CharField(max_length=255, unique=True)
    name = models.CharField(max_length=255, blank=True, default="")
    is_group = models.BooleanField(default=False)
    scoped = models.BooleanField(default=False)
    last_message_at = models.DateTimeField(null=True, blank=True)
    meta = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-last_message_at"]

    def __str__(self):
        kind = "group" if self.is_group else "dm"
        return f"{self.name or self.jid} ({kind}{', scoped' if self.scoped else ''})"


class WaMessage(models.Model):
    DIRECTION_CHOICES = [("in", "in"), ("out", "out")]

    chat = models.ForeignKey(WaChat, on_delete=models.CASCADE, related_name="messages")
    external_id = models.CharField(max_length=255)
    sender_jid = models.CharField(max_length=255, blank=True, default="")
    sender_name = models.CharField(max_length=255, blank=True, default="")
    phone = models.CharField(max_length=64, null=True, blank=True)
    direction = models.CharField(max_length=8, choices=DIRECTION_CHOICES, default="in")
    body = models.TextField()
    ts = models.DateTimeField(db_index=True)
    raw = models.JSONField(default=dict, blank=True)

    class Meta:
        unique_together = [("chat", "external_id")]
        ordering = ["-ts"]

    def __str__(self):
        return f"{self.chat.jid}:{self.external_id}"
