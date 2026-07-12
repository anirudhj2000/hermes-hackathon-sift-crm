# Building workflows

> How to turn a user request into a table + a valid workflow that fills it. Read this before you call create_table or create_workflow.

You build a data pipeline in three moves: **design a table**, **build a workflow
that targets it**, **run it**. A workflow never invents its own columns — the
target table's columns ARE the extraction schema.

## 1. Design the table (`create_table`)

Pick columns that answer the question the user actually asked, not everything a
message might contain. Fewer, sharper columns extract more reliably.

- `columns`: list of `{name, type, description, options?}`
  - `type` is one of `text | number | date | bool | enum`
  - `enum` REQUIRES an `options` list; the extractor will only ever emit one of them
  - `description` is read by the extractor at run time — write it as an instruction
    ("Lead's company, from the email domain or signature"), not just a label
- `dedupe_keys`: the subset of columns that identifies one real-world row, so
  repeated messages about the same thing merge instead of duplicating.

**Choosing dedupe keys** — this is the most important decision:
- Prefer a stable identifier the message text carries: `order_id`, `invoice_id`,
  `email`, `phone`.
- If there's no natural id, use the person/company (`person`, `company`).
- Empty `dedupe_keys` means **every message becomes a new row** — only do this for
  append-only logs.
- A row is only merged when ALL dedupe key values match (compared as strings).
  Rows where every dedupe key came out null are dropped (nothing to merge on).

## 2. Build the workflow (`create_workflow`)

DSL shape (validated by `pipelines/dsl.py` — get any field wrong and the call is
rejected with the exact error):

```json
{
  "name": "Leads — WhatsApp sync (14d)",
  "trigger": "manual",
  "table": "leads",
  "steps": [
    {"type": "fetch",  "source": "whatsapp", "since_days": 14},
    {"type": "filter", "instruction": "keep messages asking about pricing, a demo, a trial, or buying"},
    {"type": "extract"},
    {"type": "upsert", "dedupe_on": ["person"]}
  ]
}
```

Rules that the validator enforces:
- `table` must be the slug of an **already-created** table. Call `create_table`
  first and use the slug it returns — never guess a slug.
- **Step order matters** and the engine runs them top to bottom:
  `fetch` (one or more) → `filter` (optional) → `extract` (required) →
  `upsert` (required).
- `fetch`: `source` must be a declared connector. Use EITHER `since_days` (int ≥ 1)
  OR a `from_date`/`to_date` ISO range — never both. `chat_jids` is WhatsApp-only.
- `filter`: a plain-language `instruction`. Optional but recommended — it drops
  irrelevant messages before extraction, which keeps the table clean and cheap.
- `extract`: takes **NO fields**. Adding `"fields"` is a hard validation error.
- `upsert`: `dedupe_on` is optional and defaults to the table's `dedupe_keys`.
  Only pass it to override; every name must be a real column.

## 3. Triggers — one-shot vs. kept fresh

- `"manual"` — runs only when the user (or you, via `run_workflow`) starts it.
- `{"type": "interval", "minutes": N}` — the scheduler re-runs it every N minutes
  automatically. Use this whenever the user says "keep it updated", "every 30
  minutes", "continuously", etc. Minimum 1 minute.

## Multi-source workflows

You can add more than one `fetch` step to pull WhatsApp **and** Gmail into the same
table. The catch is dedupe: WhatsApp rows are keyed by `phone`, Gmail rows by
`email`, so the same person won't merge across channels unless your dedupe key is
something both carry (e.g. `company`, or an id extracted from the body). If cross-
channel merging matters, design a dedupe key both sources can populate.

## After building

Call `run_workflow` to kick off the first run. It returns a `run_id`; the run
executes in the background and the row counts land on the Tables page. Every row
carries provenance back to the exact source messages it came from.

## Before you build — reuse first

Read `workflows/` (they're listed in your boot context) and reuse or re-run an
existing workflow if one already does the job, instead of creating a duplicate.
