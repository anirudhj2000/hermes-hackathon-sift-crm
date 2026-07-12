"""Workflow engine (CONTRACTS v2).

`start_run(workflow)` creates a WorkflowRun and interprets the workflow DSL
in a background thread: fetch -> optional filter -> extract (typed against
the target table's columns) -> upsert into Records with provenance.
Appends human-readable lines to run.log (saved after each step) and fills
run.stats with exactly:
{"fetched", "kept", "rows_created", "rows_updated", "table"}
"""

import re
import threading
import traceback

from django.db import close_old_connections
from django.utils import timezone

from crm.models import DataTable, Record, Workflow, WorkflowRun

from .extractor import extract as extract_record
from .sources import gmail_composio, whatsapp

SOURCES = {"whatsapp": whatsapp, "gmail": gmail_composio}


def start_run(workflow: Workflow) -> WorkflowRun:
    """Create a WorkflowRun and execute the workflow in a background thread."""
    run = WorkflowRun.objects.create(workflow=workflow, status="pending")
    thread = threading.Thread(target=_execute, args=(run.pk,), daemon=True)
    thread.start()
    return run


def _log(run: WorkflowRun, line: str):
    run.log += line + "\n"


def _local_filter(bodies: list[str], instruction: str) -> list[bool]:
    """Fallback keyword filter when agentcore's client is unavailable."""
    keywords = [w for w in re.findall(r"[a-z]+", instruction.lower()) if len(w) > 3]
    if not keywords:
        return [True] * len(bodies)
    return [any(k in (b or "").lower() for k in keywords) for b in bodies]


def _filter_relevant(bodies: list[str], instruction: str) -> list[bool]:
    try:
        from agentcore.hermes_client import get_client  # lazy: may not exist yet

        flags = get_client().filter_relevant(bodies, instruction)
        if isinstance(flags, list) and len(flags) == len(bodies):
            return [bool(f) for f in flags]
    except Exception:
        pass
    return _local_filter(bodies, instruction)


def _context_for(msg: dict) -> dict:
    return {
        "source": msg.get("source"),
        "external_id": msg.get("external_id"),
        "sender_name": msg.get("sender_name"),
        "chat_name": msg.get("chat_name"),
        "phone": msg.get("phone"),
        "email": msg.get("email"),
        "subject": msg.get("subject"),
        "ts": msg.get("ts"),
        "direction": msg.get("direction"),
    }


def _provenance(msg: dict) -> dict:
    prov = {
        "source": msg.get("source", "whatsapp"),
        "external_id": msg.get("external_id", ""),
    }
    if msg.get("ts"):
        prov["ts"] = str(msg["ts"])
    return prov


def _dedupe_signature(data: dict, dedupe_on: list) -> tuple:
    """Str-compare signature across all dedupe key values."""
    return tuple(str(data.get(key)) for key in dedupe_on)


def _upsert_record(table, msg, dedupe_on, index, stats, created_ids, updated_ids):
    """Match a Record where ALL dedupe key values are equal (str compare);
    merge fills null/missing fields; provenance appended to `sources`.
    Empty dedupe_on => always insert."""
    data = msg.get("extracted") or {}
    if all(v is None for v in data.values()):
        return None  # nothing extracted; skip the row entirely
    prov = _provenance(msg)

    record = None
    if dedupe_on:
        if all(data.get(key) is None for key in dedupe_on):
            return None  # nothing to dedupe on; avoid unmergeable duplicates
        record = index.get(_dedupe_signature(data, dedupe_on))

    if record is None:
        record = Record.objects.create(table=table, data=data, sources=[prov])
        stats["rows_created"] += 1
        created_ids.add(record.pk)
        if dedupe_on:
            index[_dedupe_signature(data, dedupe_on)] = record
        return record

    # Merge: fill null/missing fields, append provenance.
    changed = False
    merged = dict(record.data or {})
    for key, value in data.items():
        if value is not None and merged.get(key) in (None, ""):
            merged[key] = value
            changed = True
    sources = list(record.sources or [])
    if not any(
        s.get("source") == prov["source"] and s.get("external_id") == prov["external_id"]
        for s in sources
        if isinstance(s, dict)
    ):
        sources.append(prov)
        changed = True
    if changed:
        record.data = merged
        record.sources = sources
        record.save()
    if record.pk not in created_ids and record.pk not in updated_ids:
        updated_ids.add(record.pk)
        stats["rows_updated"] += 1
    return record


def _execute(run_id: int):
    close_old_connections()
    run = WorkflowRun.objects.get(pk=run_id)
    run.status = "running"
    run.started_at = timezone.now()
    dsl = run.workflow.dsl or {}
    stats = {
        "fetched": 0,
        "kept": 0,
        "rows_created": 0,
        "rows_updated": 0,
        "table": dsl.get("table"),
    }
    run.stats = stats
    _log(run, f"Run {run.pk} started for workflow '{run.workflow.name}'.")
    run.save()

    messages: list[dict] = []
    created_ids: set[int] = set()
    updated_ids: set[int] = set()

    try:
        table = DataTable.objects.filter(slug=dsl.get("table")).first()
        if table is None:
            raise ValueError(f"target table {dsl.get('table')!r} does not exist")
        stats["table"] = table.slug

        for step in dsl.get("steps", []):
            step_type = step.get("type")

            if step_type == "fetch":
                source_name = step["source"]
                params = {
                    key: step[key]
                    for key in ("since_days", "from_date", "to_date", "chat_jids")
                    if step.get(key) is not None
                }
                fetched = SOURCES[source_name].fetch(**params)
                for msg in fetched:
                    msg = dict(msg)
                    msg["source"] = source_name
                    messages.append(msg)
                stats["fetched"] += len(fetched)
                stats["kept"] = len(messages)
                if "since_days" in params:
                    window = f"last {params['since_days']} days"
                else:
                    window = f"{params.get('from_date', 'beginning')} → {params.get('to_date', 'now')}"
                narrow = f", {len(params['chat_jids'])} chats" if params.get("chat_jids") else ""
                _log(run, f"fetch: {len(fetched)} messages from {source_name} ({window}{narrow}).")

            elif step_type == "filter":
                instruction = step["instruction"]
                flags = _filter_relevant([m.get("body", "") for m in messages], instruction)
                before = len(messages)
                messages = [m for m, keep in zip(messages, flags) if keep]
                stats["kept"] = len(messages)
                _log(run, f"filter: kept {len(messages)} of {before} messages ('{instruction}').")

            elif step_type == "extract":
                for msg in messages:
                    msg["extracted"] = extract_record(
                        msg.get("body", ""), table.columns, _context_for(msg)
                    )
                _log(
                    run,
                    f"extract: typed {len(table.columns or [])} columns "
                    f"({', '.join(table.column_names())}) from {len(messages)} messages.",
                )

            elif step_type == "upsert":
                dedupe_on = step.get("dedupe_on")
                if dedupe_on is None:
                    dedupe_on = list(table.dedupe_keys or [])
                # Pre-index existing rows by dedupe signature (str compare).
                index = {}
                if dedupe_on:
                    for existing in table.records.all():
                        index[_dedupe_signature(existing.data or {}, dedupe_on)] = existing
                for msg in messages:
                    _upsert_record(
                        table, msg, dedupe_on, index, stats, created_ids, updated_ids
                    )
                _log(
                    run,
                    "upsert: rows +{rows_created} created, {rows_updated} updated"
                    " into '{table}'.".format(**stats),
                )

            else:
                _log(run, f"skipping unknown step type: {step_type!r}")

            run.stats = stats
            run.save()

        run.status = "done"
        _log(run, "Run finished successfully.")
    except Exception as exc:  # noqa: BLE001 - report any step failure on the run
        run.status = "error"
        _log(run, f"ERROR: {exc}")
        _log(run, traceback.format_exc().strip())
    finally:
        run.stats = stats
        run.finished_at = timezone.now()
        try:
            run.save()
        except Exception:
            # The DB may have restarted under this thread — reconnect and retry
            # once so the run doesn't stay 'running' forever.
            try:
                close_old_connections()
                run.save()
            except Exception:
                pass  # the scheduler's zombie reaper will mark it failed
        _write_run_summary(run)
        close_old_connections()


def _write_run_summary(run: WorkflowRun):
    """Append a short markdown summary to workspace/runs/<workflow-slug>.md."""
    try:
        from agentcore.workspace import append_run_summary

        append_run_summary(run)
    except Exception:
        pass  # workspace bookkeeping must never break a run
