"""URLs for the pipelines app. The integrator mounts this under `api/`
(same convention as crm.urls), yielding POST /api/ingest/whatsapp."""

from django.urls import path

from .ingest_views import ingest_whatsapp

urlpatterns = [
    path("ingest/whatsapp", ingest_whatsapp, name="ingest-whatsapp"),
]
