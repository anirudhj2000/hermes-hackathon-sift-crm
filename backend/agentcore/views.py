"""POST /api/agent/chat — SSE stream per CONTRACTS.md."""

import json
import uuid

from django.http import JsonResponse, StreamingHttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from . import tools
from .hermes_client import get_client

SYSTEM_PROMPT = (
    "You are the agent inside an agentic CRM. You help the user import "
    "conversations from WhatsApp and Gmail, build workflows that extract and "
    "tag contacts, and answer questions about their CRM data. Use the "
    "available tools: create workflows with valid DSL, then run them. "
    "WhatsApp is scope-first: workflows can only fetch chats/groups the user "
    "has scoped on the WhatsApp page — call list_whatsapp_chats to see them, "
    "and if it is empty ask the user to sync and scope chats there before "
    "creating WhatsApp workflows. Fetch steps take since_days or a "
    "from_date/to_date range, and optionally chat_jids from the scoped list. "
    "Narrate briefly what you are doing."
)

MAX_TURNS = 12


def _system_message():
    """SYSTEM_PROMPT grounded with the agent workspace boot context (AGENT.md,
    connector registry, existing workflows). Injected for every chat request,
    on both the real HermesClient and MockHermesClient paths."""
    try:
        from .workspace import boot_context

        context = boot_context()
    except Exception:
        context = ""
    if context:
        return SYSTEM_PROMPT + "\n\n--- AGENT WORKSPACE ---\n" + context
    return SYSTEM_PROMPT


def _sse(event, data):
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@csrf_exempt
@require_POST
def agent_chat(request):
    try:
        payload = json.loads(request.body or b"{}")
    except ValueError:
        return JsonResponse({"error": "invalid JSON body"}, status=400)

    message = payload.get("message") or ""
    chat_id = payload.get("chat_id") or uuid.uuid4().hex

    response = StreamingHttpResponse(
        _stream(message, chat_id), content_type="text/event-stream"
    )
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


def _stream(message, chat_id):
    client = get_client()
    messages = [
        {"role": "system", "content": _system_message()},
        {"role": "user", "content": message},
    ]

    for _ in range(MAX_TURNS):
        text_parts = []
        tool_calls = []

        for event in client.chat(messages, tools.TOOL_SCHEMAS):
            if event["type"] == "text":
                text_parts.append(event["text"])
                yield _sse("token", {"text": event["text"]})
            elif event["type"] == "tool_call":
                yield _sse("tool", {"name": event["name"], "args": event["args"]})
                tool_calls.append(event)

        if not tool_calls:
            break  # assistant finished without calling a tool

        assistant_msg = {
            "role": "assistant",
            "content": "".join(text_parts) or None,
            "tool_calls": [],
        }
        executed = []
        for call in tool_calls:
            call_id = call.get("id") or f"call_{uuid.uuid4().hex[:8]}"
            assistant_msg["tool_calls"].append({
                "id": call_id,
                "type": "function",
                "function": {
                    "name": call["name"],
                    "arguments": json.dumps(call["args"]),
                },
            })
            executed.append((call_id, call))
        messages.append(assistant_msg)

        for call_id, call in executed:
            result = tools.execute(call["name"], call["args"])

            if call["name"] == "create_workflow" and "workflow_id" in result:
                _attach_chat_id(result["workflow_id"], chat_id)
                yield _sse("workflow_created", {
                    "workflow": {
                        "id": result["workflow_id"],
                        "name": result["name"],
                        "dsl": result["dsl"],
                    }
                })
            elif call["name"] == "run_workflow" and "run_id" in result:
                yield _sse("run_started", {
                    "run_id": result["run_id"],
                    "workflow_id": call["args"].get("workflow_id"),
                })

            messages.append({
                "role": "tool",
                "tool_call_id": call_id,
                "content": json.dumps(result),
            })

    yield _sse("done", {"chat_id": chat_id})


def _attach_chat_id(workflow_id, chat_id):
    try:
        from crm.models import Workflow

        Workflow.objects.filter(pk=workflow_id).update(created_by_chat_id=chat_id)
    except Exception:
        pass  # bookkeeping only; never break the stream
