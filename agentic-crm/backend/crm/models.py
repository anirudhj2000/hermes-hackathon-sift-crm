from django.db import models


class Contact(models.Model):
    name = models.CharField(max_length=255)
    phone = models.CharField(max_length=64, null=True, blank=True)
    email = models.CharField(max_length=255, null=True, blank=True)
    company = models.CharField(max_length=255, null=True, blank=True)
    tags = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Interaction(models.Model):
    SOURCE_CHOICES = [("whatsapp", "whatsapp"), ("gmail", "gmail")]
    DIRECTION_CHOICES = [("in", "in"), ("out", "out")]

    contact = models.ForeignKey(
        Contact,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="interactions",
    )
    source = models.CharField(max_length=16, choices=SOURCE_CHOICES)
    external_id = models.CharField(max_length=255)
    direction = models.CharField(max_length=8, choices=DIRECTION_CHOICES)
    body = models.TextField()
    ts = models.DateTimeField()
    extracted = models.JSONField(default=dict, blank=True)

    class Meta:
        unique_together = [("source", "external_id")]
        ordering = ["-ts"]

    def __str__(self):
        return f"{self.source}:{self.external_id}"


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
