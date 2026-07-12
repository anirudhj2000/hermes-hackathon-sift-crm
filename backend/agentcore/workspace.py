"""Agent workspace — filesystem jail + declarative connector registry.

The workspace folder (default <repo>/workspace, override with the
AGENT_WORKSPACE_ROOT env var / setting) is the agent's entire world:

  AGENT.md      identity/grounding (read-only to the agent)
  connectors/   declarative connector descriptors, *.yaml (read-only)
  schemas/      JSON Schemas, e.g. workflow.schema.json (read-only)
  workflows/    workflow documents the agent writes (writable)
  runs/         markdown run summaries (writable)

Secrets live outside the workspace by construction; nothing here is
denylisted, but paths must stay inside the root (no absolute paths, no '..').
"""

import json
import os
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BOOT_CONTEXT_MAX_BYTES = 4096
AGENT_WRITABLE_DIRS = ("workflows", "runs")
FALLBACK_SOURCES = {"whatsapp", "gmail"}

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class WorkspaceError(ValueError):
    """Raised on jail escapes and other workspace violations."""


# ---------------------------------------------------------------------------
# Root + jail
# ---------------------------------------------------------------------------

def workspace_root() -> Path:
    root = os.environ.get("AGENT_WORKSPACE_ROOT")
    if not root:
        try:  # settings may fold in its own default/override
            from django.conf import settings

            root = getattr(settings, "AGENT_WORKSPACE_ROOT", None)
        except Exception:
            root = None
    return Path(root) if root else REPO_ROOT / "workspace"


def safe_path(rel) -> Path:
    """Resolve `rel` inside the workspace root. Raises WorkspaceError on
    absolute paths, '..' components, or anything (post-realpath, so symlinks
    included) that lands outside the root."""
    rel = str(rel if rel is not None else "").strip()
    if rel.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", rel):
        raise WorkspaceError(f"absolute paths are not allowed: {rel!r}")
    parts = Path(rel).parts
    if ".." in parts:
        raise WorkspaceError(f"'..' is not allowed in workspace paths: {rel!r}")
    root = Path(os.path.realpath(workspace_root()))
    candidate = Path(os.path.realpath(root / rel)) if rel else root
    if candidate != root and root not in candidate.parents:
        raise WorkspaceError(f"path escapes the agent workspace: {rel!r}")
    return candidate


def is_agent_writable(rel) -> bool:
    """The agent may only write under workflows/ and runs/."""
    parts = Path(str(rel or "")).parts
    return len(parts) >= 2 and parts[0] in AGENT_WRITABLE_DIRS


# ---------------------------------------------------------------------------
# Connector registry
# ---------------------------------------------------------------------------

def load_registry() -> list[dict]:
    """Parse connectors/*.yaml into a list of connector dicts."""
    connectors = []
    cdir = workspace_root() / "connectors"
    if not cdir.is_dir():
        return connectors
    try:
        import yaml
    except ImportError:
        return connectors
    for path in sorted(list(cdir.glob("*.yaml")) + list(cdir.glob("*.yml"))):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(data, dict) and isinstance(data.get("name"), str) and data["name"].strip():
            data["_file"] = path.name
            connectors.append(data)
    return connectors


def get_valid_sources() -> set[str]:
    return {c["name"] for c in load_registry()}


def _capability_line(connector: dict) -> str:
    caps = []
    for cap in connector.get("provides") or []:
        if not isinstance(cap, dict):
            continue
        params = cap.get("params") or {}
        args = ", ".join(f"{k}: {v}" for k, v in params.items())
        caps.append(f"{cap.get('capability', '?')}({args}) -> {cap.get('returns', '?')}")
    return "; ".join(caps) or "(none declared)"


# ---------------------------------------------------------------------------
# Boot context
# ---------------------------------------------------------------------------

def boot_context() -> str:
    """AGENT.md + compact registry rendering + workflows/ listing, <= ~4KB."""
    root = workspace_root()
    sections = []

    agent_md = root / "AGENT.md"
    if agent_md.is_file():
        sections.append(agent_md.read_text(encoding="utf-8").strip())

    try:
        from crm.models import Connection

        auth_status = {c.source: c.status for c in Connection.objects.all()}
    except Exception:
        auth_status = {}

    reg_lines = ["## Connector registry (the ONLY sources you may use)"]
    registry = load_registry()
    if registry:
        for c in registry:
            reg_lines.append(
                f"- {c['name']} (type: {c.get('type', '?')}) — "
                f"capabilities: {_capability_line(c)} — "
                f"auth: {auth_status.get(c['name'], 'disconnected')}"
            )
    else:
        reg_lines.append("- (no connectors declared)")
    sections.append("\n".join(reg_lines))

    table_lines = ["## Tables (existing data tables — target these in workflows)"]
    try:
        from crm.models import DataTable

        tables = list(DataTable.objects.order_by("created_at"))
        for t in tables:
            cols = ", ".join(t.column_names())
            keys = f" (dedupe: {', '.join(t.dedupe_keys)})" if t.dedupe_keys else ""
            table_lines.append(f"- {t.slug}: {cols}{keys}")
        if not tables:
            table_lines.append("- (none yet — create one with create_table)")
    except Exception:
        table_lines.append("- (unavailable)")
    sections.append("\n".join(table_lines))

    wf_lines = ["## Existing workflows (check before creating duplicates)"]
    wf_dir = root / "workflows"
    docs = sorted(wf_dir.glob("*.json")) if wf_dir.is_dir() else []
    for path in docs:
        try:
            desc = json.loads(path.read_text(encoding="utf-8")).get("description") or ""
        except Exception:
            desc = "(unreadable)"
        wf_lines.append(f"- {path.name}: {desc}")
    if not docs:
        wf_lines.append("- (none yet)")
    sections.append("\n".join(wf_lines))

    text = "\n\n".join(sections)
    if len(text.encode("utf-8")) > BOOT_CONTEXT_MAX_BYTES:
        text = text.encode("utf-8")[: BOOT_CONTEXT_MAX_BYTES - 15].decode("utf-8", "ignore")
        text += "\n…[truncated]"
    return text


# ---------------------------------------------------------------------------
# Workflow documents (file-first persistence)
# ---------------------------------------------------------------------------

def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return slug or "workflow"


def workflow_doc_from_dsl(name: str, dsl: dict, created_by: str = "agent", chat_id=None) -> dict:
    """Build a workflow document (per schemas/workflow.schema.json) from the
    pinned DSL shape."""
    steps = dsl.get("steps") or []
    requires = []
    for step in steps:
        if isinstance(step, dict) and step.get("type") == "fetch":
            src = step.get("source")
            if src and src not in requires:
                requires.append(src)
    return {
        "id": slugify(name),
        "version": 1,
        "created_by": created_by,
        "chat_id": chat_id,
        "description": name,
        "requires": requires,
        "trigger": dsl.get("trigger", "manual"),
        "table": dsl.get("table"),
        "steps": steps,
    }


def validate_workflow_doc(doc, valid_sources=None) -> list[str]:
    """Hand-rolled validation against schemas/workflow.schema.json semantics.
    Returns a list of error strings (empty = valid)."""
    errors: list[str] = []
    if not isinstance(doc, dict):
        return ["workflow document must be a JSON object"]

    wf_id = doc.get("id")
    if not isinstance(wf_id, str) or not _SLUG_RE.match(wf_id or ""):
        errors.append("'id' must be a lowercase slug ([a-z0-9-])")
    version = doc.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        errors.append("'version' must be an integer >= 1")
    if not isinstance(doc.get("created_by"), str) or not doc["created_by"].strip():
        errors.append("'created_by' must be a non-empty string")
    chat_id = doc.get("chat_id")
    if chat_id is not None and not isinstance(chat_id, str):
        errors.append("'chat_id' must be a string or null")
    description = doc.get("description")
    if not isinstance(description, str) or not description.strip():
        errors.append("'description' must be a non-empty string")
    table = doc.get("table")
    if not isinstance(table, str) or not table.strip():
        errors.append("'table' must be the slug of the target data table")
    if doc.get("trigger") != "manual" and not isinstance(doc.get("trigger"), dict):
        errors.append('\'trigger\' must be "manual" or {"type": "interval", "minutes": int}')

    if valid_sources is None:
        valid_sources = get_valid_sources() or set(FALLBACK_SOURCES)
    requires = doc.get("requires")
    if (
        not isinstance(requires, list)
        or not requires
        or not all(isinstance(r, str) for r in requires)
    ):
        errors.append("'requires' must be a non-empty list of connector names")
    else:
        for r in requires:
            if r not in valid_sources:
                errors.append(
                    f"'requires' names unknown connector {r!r} — declared connectors:"
                    f" {sorted(valid_sources)}"
                )

    steps = doc.get("steps")
    if not isinstance(steps, list) or not steps:
        errors.append("'steps' must be a non-empty list")
    else:
        try:
            from pipelines.dsl import validate_dsl

            errors.extend(
                validate_dsl(
                    {
                        "name": description or "workflow",
                        "trigger": doc.get("trigger"),
                        "table": doc.get("table"),
                        "steps": steps,
                    },
                    valid_sources=valid_sources,
                )
            )
        except ImportError:
            pass
    return errors


def save_workflow_doc(doc: dict) -> str:
    """Write workflows/<id>.json; returns the workspace-relative path."""
    rel = f"workflows/{doc['id']}.json"
    path = safe_path(rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return rel


def dsl_from_doc(doc: dict, rel_path: str) -> dict:
    """DB-facing dsl JSON mirroring the file (keeps the pinned Workflow.dsl
    shape and records the backing file in '__file' — no schema migration)."""
    return {
        "name": doc.get("description") or doc.get("id"),
        "trigger": doc.get("trigger", "manual"),
        "table": doc.get("table"),
        "steps": doc.get("steps") or [],
        "__file": rel_path,
    }


def upsert_workflow_row(doc: dict, rel_path: str):
    """Upsert a crm.Workflow row for a workflow document. Matches on the
    backing file path stored in dsl['__file'], falling back to name."""
    from crm.models import Workflow

    name = doc.get("description") or doc.get("id")
    dsl = dsl_from_doc(doc, rel_path)

    existing = None
    for wf in Workflow.objects.all():
        if isinstance(wf.dsl, dict) and wf.dsl.get("__file") == rel_path:
            existing = wf
            break
    if existing is None:
        existing = Workflow.objects.filter(name=name).first()

    if existing is not None:
        existing.name = name
        existing.dsl = dsl
        if doc.get("chat_id"):
            existing.created_by_chat_id = doc["chat_id"]
        existing.save()
        return existing, False
    return (
        Workflow.objects.create(name=name, dsl=dsl, created_by_chat_id=doc.get("chat_id")),
        True,
    )


# ---------------------------------------------------------------------------
# Run summaries
# ---------------------------------------------------------------------------

def append_run_summary(run) -> None:
    """Append a short markdown summary for a finished run to
    runs/<workflow-slug>.md. Never raises."""
    try:
        wf = run.workflow
        slug = None
        if isinstance(wf.dsl, dict) and wf.dsl.get("__file"):
            slug = Path(str(wf.dsl["__file"])).stem
        slug = slug or slugify(wf.name)
        path = safe_path(f"runs/{slug}.md")
        path.parent.mkdir(parents=True, exist_ok=True)

        stats = run.stats or {}
        ts = run.finished_at or run.started_at
        ts_text = ts.isoformat(timespec="seconds") if ts else "unknown time"
        stats_line = (
            f"fetched {stats.get('fetched', 0)}, kept {stats.get('kept', 0)}, "
            f"rows +{stats.get('rows_created', 0)} created / "
            f"{stats.get('rows_updated', 0)} updated"
        )
        block = (
            f"## Run {run.pk} — {run.status} — {ts_text}\n\n"
            f"- workflow: {wf.name} (id {wf.pk})\n"
            f"- table: {stats.get('table') or '?'}\n"
            f"- stats: {stats_line}\n\n"
        )
        if not path.exists():
            block = f"# Runs — {wf.name}\n\n" + block
        with path.open("a", encoding="utf-8") as fh:
            fh.write(block)
    except Exception:
        pass  # bookkeeping only; never break a run
