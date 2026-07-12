"""Agent tools per CONTRACTS.md — names and signatures fixed.

Exports:
  TOOL_SCHEMAS — OpenAI-format tool schema list
  execute(name, args) — dispatcher returning a JSON-serializable dict
"""

import os

VALID_STEP_TYPES = {"fetch", "filter", "extract", "upsert"}

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "create_table",
            "description": "Design and save a new data table. columns is a list of {name, type: text|number|date|bool|enum, description, options? (required for enum)}; dedupe_keys is a subset of column names used to merge rows from repeated messages.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Human-readable table name, e.g. 'Orders'."},
                    "columns": {"type": "array", "description": "Column specs: {name, type, description, options?}.", "items": {"type": "object"}},
                    "dedupe_keys": {"type": "array", "description": "Column names that identify a row (subset of columns).", "items": {"type": "string"}},
                },
                "required": ["name", "columns"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_tables",
            "description": "List the existing data tables with their columns, dedupe keys, and row counts.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_records",
            "description": "Query rows from a table by slug, with optional exact-match filters on data keys.",
            "parameters": {
                "type": "object",
                "properties": {
                    "table": {"type": "string", "description": "Table slug."},
                    "filters": {"type": "object", "description": "Exact-match filters on column values, e.g. {\"paid\": true}."},
                    "limit": {"type": "integer", "description": "Max rows to return (default 20)."},
                },
                "required": ["table"],
            },
        },
    },
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
            "description": "Validate and save a workflow. The DSL needs: trigger ('manual' or {type: 'interval', minutes >= 1}), table (slug of an existing table — create it with create_table first), and steps: >=1 fetch (whatsapp|gmail, with either since_days or a from_date/to_date ISO date range, and optionally chat_jids to target specific scoped WhatsApp chats), optional filter (instruction), extract (NO fields — the table's columns are the schema), upsert (dedupe_on optional, defaults to the table's dedupe_keys). WhatsApp fetches only cover chats the user has scoped — check list_whatsapp_chats first.",
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
            "name": "list_whatsapp_chats",
            "description": "List the WhatsApp chats and groups the user has scoped for CRM use. Only these are fetchable by workflows; pass their jids as chat_jids to narrow a fetch. Returns jid, name, is_group, message_count per chat.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files in the agent workspace (AGENT.md, connectors/, schemas/, workflows/, runs/). Pass a workspace-relative directory path, or omit for the root.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Workspace-relative directory, e.g. 'workflows'. Empty = workspace root."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file from the agent workspace (e.g. 'AGENT.md', 'connectors/whatsapp.yaml', 'workflows/my-flow.json').",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Workspace-relative file path."},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write a file inside the agent workspace. Only paths under workflows/ and runs/ are writable; AGENT.md, connectors/ and schemas/ are read-only.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Workspace-relative file path under workflows/ or runs/."},
                    "content": {"type": "string", "description": "Full file content to write."},
                },
                "required": ["path", "content"],
            },
        },
    },
]


def execute(name, args):
    args = args or {}
    handlers = {
        "create_table": lambda: create_table(
            args.get("name", ""), args.get("columns") or [], args.get("dedupe_keys") or []
        ),
        "list_tables": lambda: list_tables(),
        "query_records": lambda: query_records(
            args.get("table", ""), args.get("filters"), args.get("limit", 20)
        ),
        "list_sources": lambda: list_sources(),
        "create_workflow": lambda: create_workflow(args.get("name", ""), args.get("dsl") or {}),
        "run_workflow": lambda: run_workflow(args.get("workflow_id")),
        "list_whatsapp_chats": lambda: list_whatsapp_chats(),
        "list_files": lambda: list_files(args.get("path", "")),
        "read_file": lambda: read_file(args.get("path", "")),
        "write_file": lambda: write_file(args.get("path", ""), args.get("content", "")),
    }
    handler = handlers.get(name)
    if handler is None:
        return {"error": f"unknown tool: {name}"}
    try:
        return handler()
    except Exception as exc:  # keep the SSE loop alive on tool failure
        return {"error": str(exc)}


def create_table(name, columns, dedupe_keys):
    """Validate and save a DataTable (>=1 column, valid types, dedupe_keys
    subset of column names). Returns the full table payload so the SSE
    layer can emit `table_created`."""
    from crm.models import DataTable
    from crm.serializers import validate_columns_spec, validate_dedupe_keys_spec

    if not isinstance(name, str) or not name.strip():
        return {"error": "invalid table", "details": ["'name' must be a non-empty string"]}
    errors = validate_columns_spec(columns)
    if not errors:
        errors.extend(validate_dedupe_keys_spec(dedupe_keys or [], columns))
    if errors:
        return {"error": "invalid table", "details": errors}

    table = DataTable.objects.create(
        name=name.strip(), columns=columns, dedupe_keys=dedupe_keys or []
    )
    return {
        "table_id": table.id,
        "slug": table.slug,
        "name": table.name,
        "columns": table.columns,
        "dedupe_keys": table.dedupe_keys,
    }


def list_tables():
    from django.db.models import Count

    from crm.models import DataTable

    tables = DataTable.objects.annotate(n_records=Count("records")).order_by("-created_at")
    return {
        "tables": [
            {
                "slug": t.slug,
                "name": t.name,
                "columns": t.columns,
                "dedupe_keys": t.dedupe_keys,
                "record_count": t.n_records,
            }
            for t in tables
        ]
    }


def query_records(table, filters, limit=20):
    from crm.models import DataTable

    try:
        target = DataTable.objects.get(slug=table)
    except DataTable.DoesNotExist:
        return {"error": f"no table with slug {table!r}"}
    try:
        limit = max(1, min(int(limit or 20), 100))
    except (TypeError, ValueError):
        limit = 20

    rows = []
    filters = filters if isinstance(filters, dict) else {}
    for record in target.records.order_by("-created_at", "-id"):
        data = record.data or {}
        if all(str(data.get(k)) == str(v) for k, v in filters.items()):
            rows.append({"id": record.id, "data": data, "sources": record.sources})
            if len(rows) >= limit:
                break
    return {"count": len(rows), "rows": rows}


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
    """File-first: validate the DSL (fetch sources must be connectors declared
    in the workspace registry), write workspace/workflows/<slug>.json, then
    upsert the DB Workflow row mirroring the file."""
    from . import workspace

    try:
        from pipelines.dsl import validate_dsl
    except ImportError:
        validate_dsl = _local_validate_dsl
    errors = validate_dsl(dsl)
    if errors:
        return {"error": "invalid dsl", "details": errors}

    doc = workspace.workflow_doc_from_dsl(name, dsl, created_by="agent")
    doc_errors = workspace.validate_workflow_doc(doc)
    if doc_errors:
        return {"error": "invalid workflow document", "details": doc_errors}

    rel_path = workspace.save_workflow_doc(doc)
    workflow, _created = workspace.upsert_workflow_row(doc, rel_path)
    return {
        "workflow_id": workflow.id,
        "name": workflow.name,
        "dsl": workflow.dsl,
        "file": rel_path,
    }


def list_files(path=""):
    from .workspace import safe_path, workspace_root

    target = safe_path(path)
    if not target.exists():
        return {"error": f"no such path in workspace: {path!r}"}
    if target.is_file():
        return {"path": path, "entries": [{"name": target.name, "type": "file", "size": target.stat().st_size}]}
    root = workspace_root()
    entries = []
    for child in sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name)):
        if child.name.startswith("."):
            continue  # .gitkeep etc.
        entries.append({
            "name": str(child.relative_to(root)),
            "type": "dir" if child.is_dir() else "file",
            "size": child.stat().st_size if child.is_file() else None,
        })
    return {"path": path or ".", "entries": entries}


READ_FILE_MAX_BYTES = 64 * 1024


def read_file(path):
    from .workspace import safe_path

    target = safe_path(path)
    if not target.is_file():
        return {"error": f"no such file in workspace: {path!r}"}
    data = target.read_bytes()[:READ_FILE_MAX_BYTES]
    return {"path": path, "content": data.decode("utf-8", "replace")}


def write_file(path, content):
    from .workspace import is_agent_writable, safe_path

    target = safe_path(path)  # jail check first: escapes always raise
    if not is_agent_writable(path):
        return {
            "error": (
                f"write denied: {path!r} — the agent may only write under "
                "workflows/ and runs/ (AGENT.md, connectors/, schemas/ are read-only)"
            )
        }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content if isinstance(content, str) else str(content), encoding="utf-8")
    return {"path": path, "bytes": len((content or "").encode("utf-8"))}


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


def list_whatsapp_chats():
    from django.db.models import Count

    from pipelines.models import WaChat

    chats = (
        WaChat.objects.filter(scoped=True)
        .annotate(n_messages=Count("messages"))
        .order_by("-last_message_at")
    )
    return {
        "chats": [
            {
                "jid": c.jid,
                "name": c.name or c.jid.split("@")[0],
                "is_group": c.is_group,
                "message_count": c.n_messages,
            }
            for c in chats
        ],
        "note": (
            "Only scoped chats are listed; the user controls scope on the WhatsApp page."
            if chats
            else "No chats are scoped yet — ask the user to sync and scope chats on the WhatsApp page."
        ),
    }


