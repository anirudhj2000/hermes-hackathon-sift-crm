"""Chat history — one row per user/assistant text turn, keyed by chat_id."""

from django.db import models


class ChatMessage(models.Model):
    chat_id = models.CharField(max_length=64, db_index=True)
    role = models.CharField(max_length=16)  # user | assistant
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"{self.chat_id} {self.role}: {self.content[:40]}"
