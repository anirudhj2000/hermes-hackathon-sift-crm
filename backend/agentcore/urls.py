from django.urls import path

from . import evals_views, views

urlpatterns = [
    path("agent/chat", views.agent_chat, name="agent-chat"),
    path("chats/", views.chat_list, name="chat-list"),
    path("chats/<str:chat_id>/messages/", views.chat_messages, name="chat-messages"),
    path("evals/", evals_views.evals_summary, name="evals-summary"),
]
