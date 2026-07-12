from django.urls import path

from . import views

urlpatterns = [
    path("agent/chat", views.agent_chat, name="agent-chat"),
]
