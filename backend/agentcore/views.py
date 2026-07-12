"""POST /api/agent/chat — SSE stream per CONTRACTS.md."""

import json
import uuid

from django.http import JsonResponse, StreamingHttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from . import tools, tracing
from .hermes_client import get_client

SYSTEM_PROMPT = (
    "You are the agent inside Sift, a workspace of user-defined data tables. "
    "You turn what the user wants to track into a typed table schema "
    "(create_table: columns with text|number|date|bool|enum types and dedupe "
    "keys), then build a pipeline that sifts WhatsApp/Gmail messages into "
    "typed rows (create_workflow with a valid v2 DSL whose 'table' is the "
    "slug returned by create_table, extract takes NO fields), then run it "
    "(run_workflow). Use {\"type\": \"interval\", \"minutes\": N} triggers "
    "when the user wants the table kept up to date. Answer questions about "
    "existing data with list_tables and query_records. WhatsApp is "
    "scope-first: workflows can only fetch chats/groups the user has scoped "
    "on the WhatsApp page — call list_whatsapp_chats to see them, and if it "
    "is empty ask the user to sync and scope chats there before creating "
    "WhatsApp workflows. Fetch steps take since_days or a from_date/to_date "
    "range, and optionally chat_jids from the scoped list. Narrate briefly "
    "what you are doing."
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


HISTORY_LIMIT = 20  # prior messages replayed into the prompt per request


def _load_history(chat_id):
    try:
        from .models import ChatMessage

        rows = ChatMessage.objects.filter(chat_id=chat_id).order_by(
            "-created_at", "-id"
        )[:HISTORY_LIMIT]
        return [{"role": r.role, "content": r.content} for r in reversed(rows)]
    except Exception:
        return []  # history is bookkeeping; never break the stream


def _save_turn(chat_id, user_text, assistant_text):
    try:
        from .models import ChatMessage

        ChatMessage.objects.create(chat_id=chat_id, role="user", content=user_text)
        if assistant_text.strip():
            ChatMessage.objects.create(
                chat_id=chat_id, role="assistant", content=assistant_text
            )
    except Exception:
        pass  # history is bookkeeping; never break the stream


def _stream(message, chat_id):
    client = get_client()
    model = getattr(client, "model", "mock")
    messages = [
        {"role": "system", "content": _system_message()},
        *_load_history(chat_id),
        {"role": "user", "content": message},
    ]

    # One Langfuse trace per chat request, keyed by chat_id so a multi-message
    # conversation groups into one session. No-ops when Langfuse is disabled.
    with tracing.trace("agent_chat", session_id=chat_id, input=message) as root:
        final_parts = []

        for _ in range(MAX_TURNS):
            text_parts = []
            tool_calls = []
            usage = None

            # One generation observation per model turn (tokens/cost attributed).
            with tracing.observation("generation", "llm_turn", model=model) as gen:
                gen.update(input=messages)
                for event in client.chat(messages, tools.TOOL_SCHEMAS):
                    if event["type"] == "text":
                        text_parts.append(event["text"])
                        yield _sse("token", {"text": event["text"]})
                    elif event["type"] == "usage":
                        usage = event
                    elif event["type"] == "tool_call":
                        yield _sse("tool", {"name": event["name"], "args": event["args"]})
                        tool_calls.append(event)
                gen.update(output={
                    "text": "".join(text_parts),
                    "tool_calls": [{"name": c["name"], "args": c["args"]} for c in tool_calls],
                })
                if usage:
                    in_tok, out_tok = usage.get("input_tokens"), usage.get("output_tokens")
                    gen.update(usage_details={"input": in_tok, "output": out_tok})
                    cost = tracing.price(model, in_tok, out_tok)
                    if cost:
                        gen.update(cost_details=cost)

            final_parts.append("".join(text_parts))

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
                # One span per tool call: args in, result out.
                with tracing.observation("span", f"tool:{call['name']}", input=call["args"]) as tspan:
                    result = tools.execute(call["name"], call["args"])
                    tspan.update(output=result)

                if call["name"] == "create_table" and "table_id" in result:
                    _attach_table_chat_id(result["table_id"], chat_id)
                    yield _sse("table_created", {
                        "table": {
                            "id": result["table_id"],
                            "slug": result["slug"],
                            "name": result["name"],
                            "columns": result["columns"],
                            "dedupe_keys": result["dedupe_keys"],
                        }
                    })
                elif call["name"] == "create_workflow" and "workflow_id" in result:
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

        root.update(output="".join(final_parts))

    _save_turn(chat_id, message, "\n\n".join(p for p in final_parts if p.strip()))
    tracing.flush()
    yield _sse("done", {"chat_id": chat_id})


def chat_list(request):
    """GET /api/chats/ — conversations, newest first. Title = first user msg."""
    from django.db.models import Count, Max

    from .models import ChatMessage

    rows = (
        ChatMessage.objects.values("chat_id")
        .annotate(message_count=Count("id"), updated_at=Max("created_at"))
        .order_by("-updated_at")[:50]
    )
    out = []
    for r in rows:
        title = (
            ChatMessage.objects.filter(chat_id=r["chat_id"], role="user")
            .order_by("created_at", "id")
            .values_list("content", flat=True)
            .first()
        ) or r["chat_id"]
        out.append({
            "chat_id": r["chat_id"],
            "title": title[:60],
            "message_count": r["message_count"],
            "updated_at": r["updated_at"].isoformat(),
        })
    return JsonResponse(out, safe=False)


def chat_messages(request, chat_id):
    """GET /api/chats/<chat_id>/messages/ — full transcript, oldest first."""
    from .models import ChatMessage

    return JsonResponse(
        [
            {"role": m.role, "content": m.content, "created_at": m.created_at.isoformat()}
            for m in ChatMessage.objects.filter(chat_id=chat_id)
        ],
        safe=False,
    )


def _attach_chat_id(workflow_id, chat_id):
    try:
        from crm.models import Workflow

        Workflow.objects.filter(pk=workflow_id).update(created_by_chat_id=chat_id)
    except Exception:
        pass  # bookkeeping only; never break the stream


def _attach_table_chat_id(table_id, chat_id):
    try:
        from crm.models import DataTable

        DataTable.objects.filter(pk=table_id).update(created_by_chat_id=chat_id)
    except Exception:
        pass  # bookkeeping only; never break the stream
