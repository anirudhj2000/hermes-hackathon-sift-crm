# WhatsApp integration

> How to fetch and structure WhatsApp messages. Read this before building any workflow whose fetch source is `whatsapp`.

WhatsApp is **scope-first**: workflows can only ever read chats the user has
explicitly scoped on the WhatsApp (Connections) page. This is a hard gate in the
source — an un-scoped chat is invisible, and a fetch over zero scoped chats fails
with an actionable error.

## Always do this first

Call `list_whatsapp_chats` before designing a WhatsApp workflow. It returns only
scoped chats: `{jid, name, is_group, message_count}`.

- If it's **empty**, stop and tell the user: "Open the WhatsApp page, sync your
  chats, and scope the ones you want me to read — then I'll build the pipeline."
  Do not create a WhatsApp workflow against an empty scope; it will only error.
- If it's non-empty, you may pass specific `jid`s as `chat_jids` to narrow the
  fetch, or omit `chat_jids` to read every scoped chat.

## JIDs

- A direct message: `<phone>@s.whatsapp.net` — e.g. `919812345678@s.whatsapp.net`
- A group: `<id>@g.us` — e.g. `120363041111222333@g.us`

`chat_jids` is **WhatsApp-only** — passing it on a Gmail fetch is a validation
error. Use the exact `jid` strings from `list_whatsapp_chats`; don't hand-build them.

## Message shape (what the extractor sees)

Each fetched message is:
`{external_id, chat_jid, chat_name, is_group, sender_name, phone, body, ts, direction}`

- `direction`: `"in"` = the contact messaged you; `"out"` = your own reply. For
  lead/enquiry capture you usually care about `"in"`. Say so in the filter
  instruction (e.g. "keep inbound customer messages…") if outbound noise is a problem.
- `sender_name` / `phone`: identify the person. In a **group**, every message has a
  different sender, so `phone` is the reliable per-person identifier.
- `body`: the raw text — the only place order ids, amounts, intent, etc. live.

## Good dedupe keys for WhatsApp tables

- Per-person tables (leads, contacts): **`phone`** is the most stable — names vary
  in spelling, phones don't. `person` is an acceptable fallback.
- Transactional tables (orders, tickets): a **`<thing>_id`** the message text carries
  (`order_id`, `ticket_id`). Add `phone` as a second key only if ids can collide
  across customers.

## Time windows

- "last N days" → `{"since_days": N}`.
- an explicit range → `{"from_date": "2026-07-01", "to_date": "2026-07-12"}`
  (ISO dates, `to_date` is inclusive through end of day). Never combine the two.
- A generous default (14 days) usually covers a demo's history without pulling noise.

## Groups vs. DMs

- Groups (`is_group: true`) are high-volume and multi-sender — a good `filter`
  instruction matters much more there. Scope a group only when the table really
  needs its chatter (e.g. a buyers' community for lead-spotting).
- DMs are one person per chat, so `phone`/`sender_name` cleanly identify the row.

## Live vs. mock

If the Baileys sidecar is reachable, messages are real (synced from the paired
phone into the `WaMessage` store). If not, the same store is seeded from fixtures.
Either way your DSL is identical — you never special-case the mode.
