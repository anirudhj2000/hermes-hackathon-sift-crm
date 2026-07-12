# Gmail integration

> How to fetch and structure Gmail messages. Read this before building any workflow whose fetch source is `gmail`.

Gmail is pulled through Composio's `GMAIL_FETCH_EMAILS` action when a key is
configured, and falls back to a bundled fixture otherwise. Your DSL is the same
in both modes. Unlike WhatsApp, Gmail has **no scoping step and no `chat_jids`** —
a fetch reads recent mail across the account within the time window.

## Message shape (what the extractor sees)

Each fetched message is:
`{external_id, sender_name, email, subject, body, ts, direction}`

- `email`: the sender's address — the **most stable identity** on this source.
  Names and companies vary; the address doesn't.
- `subject` AND `body` both carry signal. Threads share a subject with a `Re:`
  prefix, so a follow-up ("Re: Demo on Friday…") and the original belong to the
  same thread — dedupe on a stable key, not the subject.
- `direction`: `"in"` = received; `"out"` = a reply you sent (sender shows as
  "Me"). Filter to `"in"` when you only want customer-originated mail.
- `body`: often includes a signature block with company, role, and phone — useful
  context for extracting `company`, `phone`, or `person`.

## Good dedupe keys for Gmail tables

- Per-person / per-company tables (leads, enquiries): **`email`** — one row per
  correspondent, and follow-ups in the same thread merge into it.
- Company-level tables: **`company`** (derivable from the email domain or the
  signature) when you want one row per organisation regardless of who wrote in.
- Transactional tables (invoices, orders): an id from the body
  (`invoice_id`, `order_id`); fall back to `email` if the mail carries no id.

## Time windows

- "last N days" → `{"since_days": N}` (maps to Gmail `newer_than:Nd`).
- an explicit range → `{"from_date": "2026-07-01", "to_date": "2026-07-12"}`
  (maps to Gmail `after:`/`before:`). Never combine the two.

## Filtering

Gmail volume is lower and more structured than WhatsApp, but marketing/receipts/
notifications still creep in. A `filter` instruction like "keep messages from a
person asking about pricing, a demo, a trial, or an invoice" removes automated
noise before extraction. Skip the filter only when the table wants everything.

## Do NOT

- Don't pass `chat_jids` on a Gmail fetch — it's WhatsApp-only and will be rejected.
- Don't try to scope Gmail per-label in the DSL; the connector fetches by time
  window, and narrowing is done with the `filter` step's instruction.
