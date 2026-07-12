"""Seed the database with demo data (CONTRACTS v2). Idempotent: wipes the
crm tables (and stale v1 workflow docs) first, then seeds:

- WaChat/WaMessage store from pipelines/fixtures (all chats scoped so
  pipelines can fetch immediately)
- a sample "Leads" DataTable + a valid v2 workflow targeting it
  (file-first: workspace/workflows/<slug>.json + mirrored DB row)
- 2 Connection rows (whatsapp mock-connected, gmail disconnected)
"""

from django.core.management.base import BaseCommand

from crm.models import Connection, DataTable, Record, Workflow, WorkflowRun

LEADS_COLUMNS = [
    {"name": "person", "type": "text", "description": "Lead's name"},
    {"name": "company", "type": "text", "description": "Lead's company"},
    {
        "name": "intent",
        "type": "enum",
        "description": "What they want",
        "options": ["pricing", "demo", "trial", "purchase", "partnership"],
    },
    {"name": "source_hint", "type": "text", "description": "Where the lead came from"},
]

LEADS_DSL = {
    "name": "Leads — WhatsApp sync (14d)",
    "trigger": "manual",
    "table": "leads",
    "steps": [
        {"type": "fetch", "source": "whatsapp", "since_days": 14},
        {
            "type": "filter",
            "instruction": "keep messages that ask about pricing, a demo, a trial, or buying",
        },
        {"type": "extract"},
        {"type": "upsert", "dedupe_on": ["person"]},
    ],
}


class Command(BaseCommand):
    help = "Seed demo data: WhatsApp store, a sample table + v2 workflow, connections."

    def handle(self, *args, **options):
        # Fresh start: wipe v2 rows and any stale v1 workflow rows/files.
        WorkflowRun.objects.all().delete()
        Workflow.objects.all().delete()
        Record.objects.all().delete()
        DataTable.objects.all().delete()
        Connection.objects.all().delete()

        from agentcore import workspace

        wf_dir = workspace.workspace_root() / "workflows"
        removed = 0
        if wf_dir.is_dir():
            for path in wf_dir.glob("*.json"):
                path.unlink()
                removed += 1
        runs_dir = workspace.workspace_root() / "runs"
        if runs_dir.is_dir():
            for path in runs_dir.glob("*.md"):
                path.unlink()

        # WhatsApp store from fixtures (chats + messages via the ingest
        # upsert helper), all scoped so workflows can fetch immediately.
        from pipelines.models import WaChat
        from pipelines.wa_views import _sync_from_fixtures

        chat_count = _sync_from_fixtures()
        WaChat.objects.update(scoped=True)
        message_count = sum(c.messages.count() for c in WaChat.objects.all())

        # Sample table + a valid v2 workflow targeting it (file-first).
        leads = DataTable.objects.create(
            name="Leads", columns=LEADS_COLUMNS, dedupe_keys=["person"]
        )

        doc = workspace.workflow_doc_from_dsl(LEADS_DSL["name"], LEADS_DSL, created_by="seed")
        errors = workspace.validate_workflow_doc(doc)
        if errors:
            raise SystemExit(f"seed workflow document is invalid: {errors}")
        rel_path = workspace.save_workflow_doc(doc)
        workspace.upsert_workflow_row(doc, rel_path)

        Connection.objects.create(source="whatsapp", status="connected", meta={"mode": "mock"})
        Connection.objects.create(source="gmail", status="disconnected", meta={})

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {chat_count} WhatsApp chats ({message_count} messages, all scoped), "
                f"table '{leads.slug}', 1 workflow (wiped {removed} stale docs), 2 connections."
            )
        )
