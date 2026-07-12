"""Workflow DSL validation (see CONTRACTS.md).

DSL shape:
{ "name": str, "trigger": "manual",
  "steps": [
    {"type": "fetch",   "source": "whatsapp"|"gmail", "since_days": int},
    {"type": "filter",  "instruction": str},
    {"type": "extract", "fields": [str, ...]},
    {"type": "upsert",  "dedupe_on": ["phone","email"], "tag": str|null}
  ] }

Rules: >=1 fetch required; filter optional; extract + upsert required;
unknown step types are errors.
"""

VALID_SOURCES = {"whatsapp", "gmail"}
VALID_STEP_TYPES = {"fetch", "filter", "extract", "upsert"}
VALID_DEDUPE_KEYS = {"phone", "email"}


def validate_dsl(dsl) -> list[str]:
    """Validate a workflow DSL dict. Returns a list of error strings (empty = valid)."""
    errors: list[str] = []

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
            if source not in VALID_SOURCES:
                errors.append(
                    f"{prefix}: fetch 'source' must be one of {sorted(VALID_SOURCES)}, got {source!r}"
                )
            since_days = step.get("since_days")
            if not isinstance(since_days, int) or isinstance(since_days, bool) or since_days < 1:
                errors.append(f"{prefix}: fetch 'since_days' must be a positive integer")

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
