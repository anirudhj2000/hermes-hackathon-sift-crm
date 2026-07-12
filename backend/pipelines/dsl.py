"""Workflow DSL v2 validation (see CONTRACTS.md).

DSL shape:
{ "name": str,
  "trigger": "manual" | {"type": "interval", "minutes": int >= 1},
  "table": "<slug of an existing DataTable>",
  "steps": [
    {"type": "fetch",   "source": "whatsapp"|"gmail",
     "since_days": int                      # relative window …
     | "from_date": "YYYY-MM-DD", "to_date": "YYYY-MM-DD",  # … or absolute range
     "chat_jids": [str, ...]?},             # whatsapp only: narrow within scoped chats
    {"type": "filter",  "instruction": str},
    {"type": "extract"},                     # NO fields — table columns ARE the schema
    {"type": "upsert",  "dedupe_on": [str]?} # defaults to the table's dedupe_keys
  ] }

Rules: `table` is required and must resolve to an existing DataTable; >=1
fetch required (source must be a declared connector); filter optional;
extract + upsert required; unknown step types are errors. WhatsApp fetches
only ever see chats the user has scoped on the WhatsApp page.
"""

from datetime import date


def _parse_iso_date(value):
    if not isinstance(value, str):
        raise TypeError("date must be a string")
    return date.fromisoformat(value[:10])

VALID_SOURCES = {"whatsapp", "gmail"}  # fallback when the agent workspace is missing
VALID_STEP_TYPES = {"fetch", "filter", "extract", "upsert"}


def _registry_sources() -> set[str]:
    """Valid fetch sources = connectors declared in the agent workspace
    registry; falls back to the pinned {whatsapp, gmail} set if the
    workspace (or pyyaml) is unavailable."""
    try:
        from agentcore.workspace import get_valid_sources

        sources = get_valid_sources()
        if sources:
            return set(sources)
    except Exception:
        pass
    return set(VALID_SOURCES)


def _resolve_table(slug):
    """Return (DataTable | None, error | None) for a table slug."""
    from crm.models import DataTable  # lazy: keeps dsl importable standalone

    try:
        return DataTable.objects.get(slug=slug), None
    except DataTable.DoesNotExist:
        return None, f"'table' must be the slug of an existing table — no table {slug!r}"
    except Exception as exc:  # DB unavailable etc.
        return None, f"could not resolve table {slug!r}: {exc}"


def validate_trigger(trigger) -> list[str]:
    if trigger == "manual":
        return []
    if isinstance(trigger, dict):
        errors = []
        if trigger.get("type") != "interval":
            errors.append("'trigger' object must have type \"interval\"")
        minutes = trigger.get("minutes")
        if not isinstance(minutes, int) or isinstance(minutes, bool) or minutes < 1:
            errors.append("'trigger.minutes' must be an integer >= 1")
        return errors
    return ['\'trigger\' must be "manual" or {"type": "interval", "minutes": int >= 1}']


def validate_dsl(dsl, valid_sources=None) -> list[str]:
    """Validate a workflow DSL dict. Returns a list of error strings (empty = valid)."""
    errors: list[str] = []
    if valid_sources is None:
        valid_sources = _registry_sources()

    if not isinstance(dsl, dict):
        return ["dsl must be a JSON object"]

    name = dsl.get("name")
    if not isinstance(name, str) or not name.strip():
        errors.append("'name' must be a non-empty string")

    errors.extend(validate_trigger(dsl.get("trigger")))

    table = None
    table_slug = dsl.get("table")
    if not isinstance(table_slug, str) or not table_slug.strip():
        errors.append("'table' is required: the slug of the target table (create it first)")
    else:
        table, table_error = _resolve_table(table_slug)
        if table_error:
            errors.append(table_error)

    steps = dsl.get("steps")
    if not isinstance(steps, list) or not steps:
        errors.append("'steps' must be a non-empty list")
        return errors

    seen_types: list[str] = []
    for i, step in enumerate(steps):
        prefix = f"steps[{i}]"
        if not isinstance(step, dict):
            errors.append(f"{prefix}: each step must be an object")
            continue

        step_type = step.get("type")
        if step_type not in VALID_STEP_TYPES:
            errors.append(f"{prefix}: unknown step type {step_type!r}")
            continue
        seen_types.append(step_type)

        if step_type == "fetch":
            source = step.get("source")
            if source not in valid_sources:
                errors.append(
                    f"{prefix}: fetch 'source' must be a declared connector"
                    f" {sorted(valid_sources)}, got {source!r}"
                )
            since_days = step.get("since_days")
            from_date = step.get("from_date")
            to_date = step.get("to_date")
            has_since = since_days is not None
            has_range = from_date is not None or to_date is not None
            if has_since and has_range:
                errors.append(
                    f"{prefix}: fetch takes either 'since_days' or 'from_date'/'to_date', not both"
                )
            elif has_since:
                if not isinstance(since_days, int) or isinstance(since_days, bool) or since_days < 1:
                    errors.append(f"{prefix}: fetch 'since_days' must be a positive integer")
            elif has_range:
                parsed = {}
                for key, value in (("from_date", from_date), ("to_date", to_date)):
                    if value is None:
                        continue
                    try:
                        parsed[key] = _parse_iso_date(value)
                    except (TypeError, ValueError):
                        errors.append(
                            f"{prefix}: fetch '{key}' must be an ISO date (YYYY-MM-DD)"
                        )
                if "from_date" in parsed and "to_date" in parsed and parsed["from_date"] > parsed["to_date"]:
                    errors.append(f"{prefix}: fetch 'from_date' must not be after 'to_date'")
            else:
                errors.append(
                    f"{prefix}: fetch requires 'since_days' or a 'from_date'/'to_date' range"
                )
            chat_jids = step.get("chat_jids")
            if chat_jids is not None:
                if source != "whatsapp":
                    errors.append(f"{prefix}: 'chat_jids' is only valid for the whatsapp source")
                elif (
                    not isinstance(chat_jids, list)
                    or not chat_jids
                    or not all(isinstance(j, str) and j.strip() for j in chat_jids)
                ):
                    errors.append(
                        f"{prefix}: 'chat_jids' must be a non-empty list of chat JID strings"
                    )

        elif step_type == "filter":
            instruction = step.get("instruction")
            if not isinstance(instruction, str) or not instruction.strip():
                errors.append(f"{prefix}: filter 'instruction' must be a non-empty string")

        elif step_type == "extract":
            if "fields" in step:
                errors.append(
                    f"{prefix}: extract takes NO 'fields' — the target table's columns are the schema"
                )

        elif step_type == "upsert":
            dedupe_on = step.get("dedupe_on")
            if dedupe_on is not None:
                if not isinstance(dedupe_on, list) or not all(
                    isinstance(k, str) and k.strip() for k in dedupe_on
                ):
                    errors.append(
                        f"{prefix}: upsert 'dedupe_on' must be a list of column names"
                    )
                elif table is not None:
                    names = set(table.column_names())
                    for key in dedupe_on:
                        if key not in names:
                            errors.append(
                                f"{prefix}: upsert dedupe key {key!r} is not a column of"
                                f" table {table.slug!r}"
                            )

    if "fetch" not in seen_types:
        errors.append("workflow requires at least one 'fetch' step")
    if "extract" not in seen_types:
        errors.append("workflow requires an 'extract' step")
    if "upsert" not in seen_types:
        errors.append("workflow requires an 'upsert' step")

    return errors
