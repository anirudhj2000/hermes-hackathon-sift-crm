"""Workflow DSL validation (see CONTRACTS.md).

DSL shape:
{ "name": str, "trigger": "manual",
  "steps": [
    {"type": "fetch",   "source": "whatsapp"|"gmail",
     "since_days": int                      # relative window …
     | "from_date": "YYYY-MM-DD", "to_date": "YYYY-MM-DD",  # … or absolute range
     "chat_jids": [str, ...]?},             # whatsapp only: narrow within scoped chats
    {"type": "filter",  "instruction": str},
    {"type": "extract", "fields": [str, ...]},
    {"type": "upsert",  "dedupe_on": ["phone","email"], "tag": str|null}
  ] }

Rules: >=1 fetch required; filter optional; extract + upsert required;
unknown step types are errors. Fetch takes either since_days or a
from_date/to_date range (at least one bound). WhatsApp fetches only ever
see chats the user has scoped on the WhatsApp page.
"""

from datetime import date


def _parse_iso_date(value):
    if not isinstance(value, str):
        raise TypeError("date must be a string")
    return date.fromisoformat(value[:10])

VALID_SOURCES = {"whatsapp", "gmail"}  # fallback when the agent workspace is missing
VALID_STEP_TYPES = {"fetch", "filter", "extract", "upsert"}
VALID_DEDUPE_KEYS = {"phone", "email"}


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

    trigger = dsl.get("trigger")
    if trigger != "manual":
        errors.append("'trigger' must be \"manual\"")

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
            fields = step.get("fields")
            if (
                not isinstance(fields, list)
                or not fields
                or not all(isinstance(f, str) and f.strip() for f in fields)
            ):
                errors.append(f"{prefix}: extract 'fields' must be a non-empty list of strings")

        elif step_type == "upsert":
            dedupe_on = step.get("dedupe_on")
            if (
                not isinstance(dedupe_on, list)
                or not dedupe_on
                or not all(k in VALID_DEDUPE_KEYS for k in dedupe_on)
            ):
                errors.append(
                    f"{prefix}: upsert 'dedupe_on' must be a non-empty list drawn from"
                    f" {sorted(VALID_DEDUPE_KEYS)}"
                )
            tag = step.get("tag")
            if tag is not None and not isinstance(tag, str):
                errors.append(f"{prefix}: upsert 'tag' must be a string or null")

    if "fetch" not in seen_types:
        errors.append("workflow requires at least one 'fetch' step")
    if "extract" not in seen_types:
        errors.append("workflow requires an 'extract' step")
    if "upsert" not in seen_types:
        errors.append("workflow requires an 'upsert' step")

    return errors
