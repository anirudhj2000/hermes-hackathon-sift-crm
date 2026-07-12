"""Workflow engine (see CONTRACTS.md).

`start_run(workflow)` creates a WorkflowRun and interprets the workflow DSL
in a background thread: fetch -> optional filter -> extract -> upsert.
Appends human-readable lines to run.log (saved after each step) and fills
run.stats with exactly:
{"fetched", "kept", "contacts_created", "contacts_updated", "interactions_created"}
"""

import re
import threading
import traceback
from datetime import datetime, timezone as dt_timezone

from django.db import close_old_connections
from django.utils import timezone

from crm.models import Contact, Interaction, Workflow, WorkflowRun

from .extractor import extract as extract_fields
from .extractor import normalize_phone
from .sources import gmail_composio, whatsapp

SOURCES = {"whatsapp": whatsapp, "gmail": gmail_composio}


def start_run(workflow: Workflow) -> WorkflowRun:
    """Create a WorkflowRun and execute the workflow in a background thread."""
    run = WorkflowRun.objects.create(workflow=workflow, status="pending")
    thread = threading.Thread(target=_execute, args=(run.pk,), daemon=True)
    thread.start()
    return run


def _parse_ts(value) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if timezone.is_naive(dt):
        dt = dt.replace(tzinfo=dt_timezone.utc)
    return dt


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


def _upsert_contact(message, dedupe_on, tag, stats, created_ids, updated_ids):
    """Match/merge a Contact per CONTRACTS: match by phone OR email (first
    hit wins); merge fills null fields, appends tag if not present.

    Any match against a pre-existing contact counts as a merge: the contact
    is counted once in stats["contacts_updated"] even if no field changed."""
    extracted = message.get("extracted", {})
    phone = normalize_phone(extracted.get("phone") or message.get("phone"))
    email = (extracted.get("email") or message.get("email") or "").strip() or None
    company = extracted.get("company") or None
    name = (
        (extracted.get("name") or message.get("sender_name") or "").strip()
        or phone
        or email
        or "Unknown"
    )

    contact = None
    for key in dedupe_on:
        if key == "phone" and phone:
            contact = Contact.objects.filter(phone=phone).first()
        elif key == "email" and email:
            contact = Contact.objects.filter(email__iexact=email).first()
        if contact:
            break

    if contact is None:
        if not phone and not email:
            return None  # nothing to dedupe on; skip contact creation
        contact = Contact.objects.create(
            name=name,
            phone=phone,
            email=email,
            company=company,
            tags=[tag] if tag else [],
        )
        stats["contacts_created"] += 1
        created_ids.add(contact.pk)
        return contact

    # A message matched an existing contact: count the merge (once per contact
    # per run), regardless of whether any field actually needs filling.
    if contact.pk not in created_ids and contact.pk not in updated_ids:
        updated_ids.add(contact.pk)
        stats["contacts_updated"] += 1

    changed = False
    if not contact.phone and phone:
        contact.phone = phone
        changed = True
    if not contact.email and email:
        contact.email = email
        changed = True
    if not contact.company and company:
        contact.company = company
        changed = True
    tags = list(contact.tags or [])
    if tag and tag not in tags:
        tags.append(tag)
        contact.tags = tags
        changed = True
    if changed:
        contact.save()
    return contact


def _execute(run_id: int):
    close_old_connections()
    run = WorkflowRun.objects.get(pk=run_id)
    run.status = "running"
    run.started_at = timezone.now()
    stats = {
        "fetched": 0,
        "kept": 0,
        "contacts_created": 0,
        "contacts_updated": 0,
        "interactions_created": 0,
    }
    run.stats = stats
    dsl = run.workflow.dsl or {}
    _log(run, f"Run {run.pk} started for workflow '{run.workflow.name}'.")
    run.save()

    messages: list[dict] = []
    created_ids: set[int] = set()
    updated_ids: set[int] = set()

    try:
        for step in dsl.get("steps", []):
            step_type = step.get("type")

            if step_type == "fetch":
                source_name = step["source"]
                since_days = step["since_days"]
                fetched = SOURCES[source_name].fetch(since_days)
                for msg in fetched:
                    msg = dict(msg)
                    msg["source"] = source_name
                    messages.append(msg)
                stats["fetched"] += len(fetched)
                stats["kept"] = len(messages)
                _log(run, f"fetch: {len(fetched)} messages from {source_name} (last {since_days} days).")

            elif step_type == "filter":
                instruction = step["instruction"]
                flags = _filter_relevant([m.get("body", "") for m in messages], instruction)
                before = len(messages)
                messages = [m for m, keep in zip(messages, flags) if keep]
                stats["kept"] = len(messages)
                _log(run, f"filter: kept {len(messages)} of {before} messages ('{instruction}').")

            elif step_type == "extract":
                fields = step["fields"]
                for msg in messages:
                    msg["extracted"] = extract_fields(
                        msg.get("body", ""),
                        fields,
                        sender_name=msg.get("sender_name"),
                        phone=msg.get("phone"),
                        email=msg.get("email"),
                    )
                _log(run, f"extract: extracted {fields} from {len(messages)} messages.")

            elif step_type == "upsert":
                dedupe_on = step.get("dedupe_on", ["phone", "email"])
                tag = step.get("tag")
                for msg in messages:
                    contact = _upsert_contact(msg, dedupe_on, tag, stats, created_ids, updated_ids)
                    interaction, created = Interaction.objects.get_or_create(
                        source=msg.get("source", "whatsapp"),
                        external_id=msg["external_id"],
                        defaults={
                            "contact": contact,
                            "direction": msg.get("direction", "in"),
                            "body": msg.get("body", ""),
                            "ts": _parse_ts(msg.get("ts") or timezone.now()),
                            "extracted": msg.get("extracted", {}),
                        },
                    )
                    if created:
                        stats["interactions_created"] += 1
                    elif interaction.contact_id is None and contact is not None:
                        interaction.contact = contact
                        interaction.save(update_fields=["contact"])
                _log(
                    run,
                    "upsert: contacts +{contacts_created} created, {contacts_updated} merged into existing;"
                    " interactions +{interactions_created} created.".format(**stats),
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
        run.save()
        close_old_connections()
