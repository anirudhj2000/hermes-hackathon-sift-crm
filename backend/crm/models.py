from django.db import models
from django.utils.text import slugify

COLUMN_TYPES = ("text", "number", "date", "bool", "enum")


class DataTable(models.Model):
    """A user-defined table designed by the agent in chat (CONTRACTS v2).

    `columns` is a list of {"name", "type": text|number|date|bool|enum,
    "description", "options"?}; `dedupe_keys` is a subset of column names.
    """

    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True, blank=True)
    columns = models.JSONField(default=list)
    dedupe_keys = models.JSONField(default=list, blank=True)
    created_by_chat_id = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name)[:240] or "table"
            slug = base
            suffix = 2
            while DataTable.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base}-{suffix}"
                suffix += 1
            self.slug = slug
        super().save(*args, **kwargs)

    def column_names(self):
        return [c.get("name") for c in (self.columns or []) if isinstance(c, dict)]

    def __str__(self):
        return f"{self.name} ({self.slug})"


class Record(models.Model):
    """A typed row in a DataTable with source provenance."""

    table = models.ForeignKey(DataTable, on_delete=models.CASCADE, related_name="records")
    data = models.JSONField(default=dict)
    sources = models.JSONField(default=list)  # [{"source", "external_id", "ts"?}]
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"record {self.pk} in {self.table.slug}"


class Connection(models.Model):
    STATUS_CHOICES = [
        ("disconnected", "disconnected"),
        ("pending", "pending"),
        ("connected", "connected"),
    ]

    source = models.CharField(max_length=32, unique=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="disconnected")
    meta = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return f"{self.source} ({self.status})"


class Workflow(models.Model):
    name = models.CharField(max_length=255)
    dsl = models.JSONField()
    created_by_chat_id = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class WorkflowRun(models.Model):
    STATUS_CHOICES = [
        ("pending", "pending"),
        ("running", "running"),
        ("done", "done"),
        ("error", "error"),
    ]

    workflow = models.ForeignKey(Workflow, on_delete=models.CASCADE, related_name="runs")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="pending")
    stats = models.JSONField(default=dict, blank=True)
    log = models.TextField(default="", blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"run {self.pk} of workflow {self.workflow_id} ({self.status})"
