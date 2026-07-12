"""URLs for the pipelines app. The integrator mounts this under `api/`
(same convention as crm.urls), yielding POST /api/ingest/whatsapp plus the
v2 WhatsApp chat-scoping endpoints."""

from django.urls import path

from . import wa_views
from .ingest_views import ingest_whatsapp

urlpatterns = [
    path("ingest/whatsapp", ingest_whatsapp, name="ingest-whatsapp"),
    path("whatsapp/chats/", wa_views.list_chats, name="wa-chats"),
    path("whatsapp/chats/sync/", wa_views.sync_chats, name="wa-chats-sync"),
    path("whatsapp/chats/<int:pk>/scope/", wa_views.scope_chat, name="wa-chat-scope"),
    path("whatsapp/messages/", wa_views.list_messages, name="wa-messages"),
]
