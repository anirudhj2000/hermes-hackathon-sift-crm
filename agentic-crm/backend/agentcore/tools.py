"""Agent tools per CONTRACTS.md — names and signatures fixed.

Exports:
  TOOL_SCHEMAS — OpenAI-format tool schema list
  execute(name, args) — dispatcher returning a JSON-serializable dict
"""

import os

from django.db.models import Count

VALID_STEP_TYPES = {"fetch", "filter", "extract", "upsert"}

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "list_sources",
            "description": "List available data sources (whatsapp, gmail) with their connection status and whether they run in live or mock mode.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_workflow",
            "description": "Validate and save a workflow. The DSL must have a manual trigger and steps: >=1 fetch (whatsapp|gmail, since_days), optional filter (instruction), extract (fields), upsert (dedupe_on, tag).",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Human-readable workflow name."},
                    "dsl": {"type": "object", "description": "Workflow DSL object per the pinned schema."},
                },
                "required": ["name", "dsl"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_workflow",
            "description": "Start an asynchronous run of a previously created workflow.",
            "parameters": {
                "type": "object",
                "properties": {
                    "workflow_id": {"type": "integer", "description": "ID returned by create_workflow."},
                },
                "required": ["workflow_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_crm",
            "description": "Get simple CRM stats: contact/interaction counts, per-source breakdown, and recently used tags.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "The user's question about CRM data."},
                },
                "required": ["question"],
            },
        },
    },
]


def execute(name, args):
    args = args or {}
    handlers = {
        "list_sources": lambda: list_sources(),
        "create_workflow": lambda: create_workflow(args.get("name", ""), args.get("dsl") or {}),
        "run_workflow": lambda: run_workflow(args.get("workflow_id")),
        "query_crm": lambda: query_crm(args.get("question", "")),
    }
    handler = handlers.get(name)
    if handler is None:
        return {"error": f"unknown tool: {name}"}
    try:
        return handler()
    except Exception as exc:  # keep the SSE loop alive on tool failure
        return {"error": str(exc)}


def list_sources():
    from crm.models import Connection

    statuses = {c.source: c.status for c in Connection.objects.all()}

    def whatsapp_mode():
        import httpx

        try:
            httpx.get(os.environ.get("SIDECAR_URL", "http://localhost:3001"), timeout=0.8)
            return "live"
        except Exception:
            return "mock"

    return {
        "sources": [
            {
                "source": "whatsapp",
                "status": statuses.get("whatsapp", "disconnected"),
                "mode": whatsapp_mode(),
            },
            {
                "source": "gmail",
                "status": statuses.get("gmail", "disconnected"),
                "mode": "live" if os.environ.get("COMPOSIO_API_KEY") else "mock",
            },
        ]
    }


def _local_validate_dsl(dsl):
    """Permissive fallback used only if pipelines.dsl is not importable yet."""
    errors = []
    if not isinstance(dsl, dict):
        return ["dsl must be an object"]
    steps = dsl.get("steps")
    if not isinstance(steps, list) or not steps:
        return ["dsl.steps must be a non-empty list"]
    types = []
    for i, step in enumerate(steps):
        if not isinstance(step, dict) or "type" not in step:
            errors.append(f"step {i} must be an object with a 'type'")
            continue
        if step["type"] not in VALID_STEP_TYPES:
            errors.append(f"step {i}: unknown type {step['type']!r}")
        types.append(step["type"])
    if "fetch" not in types:
        errors.append("at least one fetch step is required")
    if "extract" not in types:
        errors.append("an extract step is required")
    if "upsert" not in types:
        errors.append("an upsert step is required")
    return errors


def create_workflow(name, dsl):
    try:
        from pipelines.dsl import validate_dsl
    except ImportError:
        validate_dsl = _local_validate_dsl
    errors = validate_dsl(dsl)
    if errors:
        return {"error": "invalid dsl", "details": errors}

    from crm.models import Workflow

    workflow = Workflow.objects.create(name=name, dsl=dsl)
    return {"workflow_id": workflow.id, "name": workflow.name, "dsl": workflow.dsl}


def run_workflow(workflow_id):
    try:
        from pipelines.engine import start_run
    except ImportError:
        return {"error": "engine not ready"}

    from crm.models import Workflow

    try:
        workflow = Workflow.objects.get(pk=workflow_id)
    except Workflow.DoesNotExist:
        return {"error": f"workflow {workflow_id} not found"}
    run = start_run(workflow)
    return {"run_id": run.id}


def query_crm(question):
    from crm.models import Contact, Interaction

    by_source = {
        row["source"]: row["n"]
        for row in Interaction.objects.values("source").annotate(n=Count("id"))
    }
    recent_tags = []
    for contact in Contact.objects.order_by("-created_at")[:50]:
        for tag in contact.tags or []:
            if tag not in recent_tags:
                recent_tags.append(tag)
        if len(recent_tags) >= 10:
            break
    return {
        "contacts": Contact.objects.count(),
        "interactions": Interaction.objects.count(),
        "by_source": by_source,
        "recent_tags": recent_tags[:10],
    }
