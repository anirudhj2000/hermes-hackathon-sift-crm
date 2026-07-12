from rest_framework import serializers

from .models import COLUMN_TYPES, Connection, DataTable, Record, Workflow, WorkflowRun


def validate_columns_spec(columns):
    """Shared column-list validation (used by the API and agent tools).
    Returns a list of error strings (empty = valid)."""
    errors = []
    if not isinstance(columns, list) or not columns:
        return ["'columns' must be a non-empty list"]
    seen = set()
    for i, col in enumerate(columns):
        prefix = f"columns[{i}]"
        if not isinstance(col, dict):
            errors.append(f"{prefix}: each column must be an object")
            continue
        name = col.get("name")
        if not isinstance(name, str) or not name.strip():
            errors.append(f"{prefix}: 'name' must be a non-empty string")
        elif name in seen:
            errors.append(f"{prefix}: duplicate column name {name!r}")
        else:
            seen.add(name)
        ctype = col.get("type")
        if ctype not in COLUMN_TYPES:
            errors.append(f"{prefix}: 'type' must be one of {list(COLUMN_TYPES)}, got {ctype!r}")
        options = col.get("options")
        if ctype == "enum":
            if (
                not isinstance(options, list)
                or not options
                or not all(isinstance(o, str) and o.strip() for o in options)
            ):
                errors.append(f"{prefix}: enum columns need a non-empty 'options' list of strings")
        elif options is not None and not isinstance(options, list):
            errors.append(f"{prefix}: 'options' must be a list")
        description = col.get("description")
        if description is not None and not isinstance(description, str):
            errors.append(f"{prefix}: 'description' must be a string")
    return errors


def validate_dedupe_keys_spec(dedupe_keys, columns):
    errors = []
    if not isinstance(dedupe_keys, list) or not all(isinstance(k, str) for k in dedupe_keys):
        return ["'dedupe_keys' must be a list of column names"]
    names = {c.get("name") for c in columns if isinstance(c, dict)}
    for key in dedupe_keys:
        if key not in names:
            errors.append(f"dedupe key {key!r} is not a column name")
    return errors


class TableSerializer(serializers.ModelSerializer):
    slug = serializers.SlugField(read_only=True)
    record_count = serializers.SerializerMethodField()

    class Meta:
        model = DataTable
        fields = [
            "id",
            "slug",
            "name",
            "columns",
            "dedupe_keys",
            "record_count",
            "created_by_chat_id",
            "created_at",
        ]
        read_only_fields = ["created_by_chat_id"]

    def get_record_count(self, obj):
        count = getattr(obj, "record_count", None)
        return count if count is not None else obj.records.count()

    def validate(self, attrs):
        columns = attrs.get("columns", getattr(self.instance, "columns", None))
        dedupe_keys = attrs.get("dedupe_keys", getattr(self.instance, "dedupe_keys", []) or [])
        errors = validate_columns_spec(columns)
        if not errors:
            errors.extend(validate_dedupe_keys_spec(dedupe_keys, columns))
        if errors:
            raise serializers.ValidationError(errors)
        return attrs


class RecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = Record
        fields = ["id", "data", "sources", "created_at", "updated_at"]


class ConnectionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Connection
        fields = ["id", "source", "status", "meta"]


class WorkflowSerializer(serializers.ModelSerializer):
    class Meta:
        model = Workflow
        fields = ["id", "name", "dsl", "created_by_chat_id", "created_at"]
        read_only_fields = ["created_by_chat_id"]


class WorkflowRunSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkflowRun
        fields = [
            "id",
            "workflow",
            "status",
            "stats",
            "log",
            "started_at",
            "finished_at",
        ]
