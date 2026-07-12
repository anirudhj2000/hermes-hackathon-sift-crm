"""Sync workspace/workflows/*.json into crm.Workflow rows.

Hand-dropped workflow files appear in the UI after running this. Each file is
validated against schemas/workflow.schema.json semantics (hand-rolled checks
in agentcore.workspace.validate_workflow_doc); invalid files are reported and
skipped.
"""

import json

from django.core.management.base import BaseCommand

from agentcore import workspace


class Command(BaseCommand):
    help = "Scan workspace/workflows/*.json, validate against the workflow schema, and upsert DB Workflow rows."

    def handle(self, *args, **options):
        root = workspace.workspace_root()
        wf_dir = root / "workflows"
        if not wf_dir.is_dir():
            self.stderr.write(self.style.ERROR(f"no workflows directory at {wf_dir}"))
            return

        valid_sources = workspace.get_valid_sources() or set(workspace.FALLBACK_SOURCES)
        created = updated = invalid = 0

        for path in sorted(wf_dir.glob("*.json")):
            rel = f"workflows/{path.name}"
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except ValueError as exc:
                invalid += 1
                self.stderr.write(self.style.WARNING(f"SKIP {rel}: invalid JSON ({exc})"))
                continue

            errors = workspace.validate_workflow_doc(doc, valid_sources=valid_sources)
            if errors:
                invalid += 1
                self.stderr.write(self.style.WARNING(f"SKIP {rel}: schema errors:"))
                for err in errors:
                    self.stderr.write(f"  - {err}")
                continue

            workflow, was_created = workspace.upsert_workflow_row(doc, rel)
            if was_created:
                created += 1
                self.stdout.write(f"CREATED workflow {workflow.pk} '{workflow.name}' from {rel}")
            else:
                updated += 1
                self.stdout.write(f"UPDATED workflow {workflow.pk} '{workflow.name}' from {rel}")

        self.stdout.write(
            self.style.SUCCESS(
                f"sync_workspace: {created} created, {updated} updated, {invalid} invalid/skipped."
            )
        )
