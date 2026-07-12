"""Seed the database with realistic demo data. Idempotent: wipes crm tables first."""

from datetime import datetime, timedelta, timezone

from django.core.management.base import BaseCommand

from crm.models import Connection, Contact, Interaction, Workflow, WorkflowRun

NOW = datetime(2026, 7, 12, 9, 0, 0, tzinfo=timezone.utc)

CONTACTS = [
    {"name": "Asha Rao", "phone": "+919812345678", "email": "asha.rao@zenithlabs.in", "company": "Zenith Labs", "tags": ["lead", "pricing"]},
    {"name": "Vikram Malhotra", "phone": "+919876501234", "email": "vikram@malhotratraders.com", "company": "Malhotra Traders", "tags": ["customer"]},
    {"name": "Priya Krishnan", "phone": "+919845098450", "email": "priya.k@chennaisoft.io", "company": "ChennaiSoft", "tags": ["lead"]},
    {"name": "Rohan Deshpande", "phone": "+919920011223", "email": "rohan.d@punefintech.com", "company": "Pune Fintech", "tags": ["demo-requested"]},
    {"name": "Sarah Whitfield", "phone": "+14155550123", "email": "sarah@brightharbor.co", "company": "Bright Harbor", "tags": ["customer", "enterprise"]},
    {"name": "Tom Okafor", "phone": "+2348012345678", "email": "tom.okafor@lagosworks.ng", "company": "LagosWorks", "tags": ["lead"]},
    {"name": "Mei Tanaka", "phone": "+818012345678", "email": "mei.tanaka@sakuradigital.jp", "company": "Sakura Digital", "tags": ["partner"]},
    {"name": "Neha Kulkarni", "phone": "+919867012345", "email": "neha@kulkarnistudio.in", "company": "Kulkarni Studio", "tags": ["lead", "pricing"]},
]

# (contact_idx, source, direction, days_ago, body)
INTERACTIONS = [
    (0, "whatsapp", "in", 1, "Hi, what's the pricing for the pro plan? We are a team of 12."),
    (0, "whatsapp", "out", 1, "Hi Asha! Pro is Rs 999/user/month, annual billing. Happy to set up a call."),
    (0, "whatsapp", "in", 0, "Thanks. Can you share a quote for 12 seats with GST?"),
    (0, "gmail", "in", 3, "Subject: Quote request\n\nHello, following up on our WhatsApp chat - please send a formal quote for 12 pro seats for Zenith Labs."),
    (1, "whatsapp", "in", 2, "Bhai, the export invoices feature is not working since yesterday. Please check."),
    (1, "whatsapp", "out", 2, "Sorry about that Vikram, we pushed a fix just now. Can you retry?"),
    (1, "whatsapp", "in", 2, "Working now. Thanks for the quick fix!"),
    (1, "gmail", "out", 6, "Subject: Renewal confirmation\n\nHi Vikram, your annual plan for Malhotra Traders renews on Aug 1. Let us know if you want to add seats."),
    (2, "whatsapp", "in", 4, "Hello, I saw your product on LinkedIn. Do you have an API for bulk contact import?"),
    (2, "whatsapp", "out", 4, "Hi Priya! Yes, we have a REST API plus CSV import. Want me to send docs?"),
    (2, "whatsapp", "in", 4, "Yes please, send to priya.k@chennaisoft.io"),
    (2, "gmail", "out", 4, "Subject: API docs\n\nHi Priya, as promised - API documentation and a sandbox key are attached. Ping me with questions."),
    (3, "whatsapp", "in", 5, "Can we get a demo this Thursday? Our founder wants to see the workflow builder."),
    (3, "whatsapp", "out", 5, "Absolutely Rohan, Thursday 4pm IST works. Sending a calendar invite."),
    (3, "gmail", "out", 5, "Subject: Demo - Thursday 4pm IST\n\nHi Rohan, calendar invite attached for the product demo. Agenda: workflow builder, WhatsApp import, pricing."),
    (3, "gmail", "in", 2, "Subject: Re: Demo - Thursday 4pm IST\n\nGreat session, thanks! Please share pricing for the startup tier and the SOC2 report."),
    (4, "gmail", "in", 8, "Subject: Enterprise SSO\n\nHi team, Bright Harbor needs SAML SSO before we can roll out to the whole org. What's the timeline?"),
    (4, "gmail", "out", 7, "Subject: Re: Enterprise SSO\n\nHi Sarah, SAML is shipping this quarter. We can enable the beta for you next week."),
    (4, "gmail", "in", 6, "Subject: Re: Enterprise SSO\n\nBeta works for us. Please loop in our IT lead."),
    (4, "whatsapp", "in", 1, "Quick one - can we bump our seat count from 40 to 55 this month?"),
    (5, "whatsapp", "in", 6, "Good day! Does your CRM work with WhatsApp Business numbers in Nigeria?"),
    (5, "whatsapp", "out", 6, "Hi Tom, yes - any WhatsApp number works via QR pairing. Want a trial account?"),
    (5, "whatsapp", "in", 5, "Yes, set me up please. We have a 5 person sales team at LagosWorks."),
    (6, "gmail", "in", 10, "Subject: Partnership inquiry\n\nHello, Sakura Digital resells SaaS tools in Japan. Interested in a reseller agreement for your CRM."),
    (6, "gmail", "out", 9, "Subject: Re: Partnership inquiry\n\nHi Mei, we'd love to explore this. Sharing our partner deck and margin structure."),
    (6, "gmail", "in", 7, "Subject: Re: Partnership inquiry\n\nDeck looks good. Can we schedule a call next week to discuss localization?"),
    (7, "whatsapp", "in", 3, "Hi! What is the price for just 2 users? We are a small design studio."),
    (7, "whatsapp", "out", 3, "Hi Neha! Starter plan is Rs 499/user/month, monthly billing is fine for 2 seats."),
    (7, "whatsapp", "in", 2, "Ok. Is there a free trial? And does it import old WhatsApp chats?"),
    (7, "gmail", "in", 1, "Subject: Trial signup\n\nHi, signed up for the trial under neha@kulkarnistudio.in. How do I connect my WhatsApp?"),
]

WORKFLOW_DSL = {
    "name": "gmail-weekly-import",
    "trigger": "manual",
    "steps": [
        {"type": "fetch", "source": "gmail", "since_days": 7},
        {"type": "filter", "instruction": "keep messages about pricing, quotes, or demo requests"},
        {"type": "extract", "fields": ["name", "phone", "email", "company", "intent"]},
        {"type": "upsert", "dedupe_on": ["phone", "email"], "tag": "gmail-import"},
    ],
}


class Command(BaseCommand):
    help = "Seed demo contacts, interactions, a sample workflow, and connection rows."

    def handle(self, *args, **options):
        WorkflowRun.objects.all().delete()
        Workflow.objects.all().delete()
        Interaction.objects.all().delete()
        Contact.objects.all().delete()
        Connection.objects.all().delete()

        contacts = [Contact.objects.create(**data) for data in CONTACTS]

        counters = {"whatsapp": 0, "gmail": 0}
        for idx, source, direction, days_ago, body in INTERACTIONS:
            counters[source] += 1
            prefix = "wa" if source == "whatsapp" else "gm"
            Interaction.objects.create(
                contact=contacts[idx],
                source=source,
                external_id=f"{prefix}-seed-{counters[source]:04d}",
                direction=direction,
                body=body,
                ts=NOW - timedelta(days=days_ago, hours=counters[source] % 8),
                extracted={},
            )

        Workflow.objects.create(name="gmail-weekly-import", dsl=WORKFLOW_DSL)

        for source in ("whatsapp", "gmail"):
            Connection.objects.get_or_create(
                source=source, defaults={"status": "disconnected", "meta": {}}
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {len(contacts)} contacts, {len(INTERACTIONS)} interactions, "
                "1 workflow, 2 connections."
            )
        )
