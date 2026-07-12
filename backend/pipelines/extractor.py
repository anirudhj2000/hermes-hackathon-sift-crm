"""Typed field extraction against a table schema (CONTRACTS v2).

`extract(body, columns, context)` returns {column_name: typed value | None}
for every column in the target table. It delegates to
agentcore.hermes_client.get_client().extract (real LLM structured output, or
the mock) and fills anything missing with the local per-type heuristics in
`heuristic_extract_typed`, then coerces every value to its column type.

Mock heuristics per type:
  number — quantity phrases ("12 seats", "4 people") or the first number
  date   — ISO/verbal dates in the body, else the message timestamp
  bool   — positive/negative cue words near the column concept
  enum   — option keyword match against the body
  text   — column-name aware: phones/emails by regex, names from the sender,
           companies from "at/from <X>" or email domain, *_id columns get a
           stable id derived from the sender, plans/items by product words
"""

import re

PHONE_RE = re.compile(r"(?:\+?\d[\d\-\s()]{7,}\d)")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
COMPANY_RE = re.compile(
    r"\b(?:at|from|with)\s+([A-Z][A-Za-z0-9&.\-]*(?:\s+[A-Z][A-Za-z0-9&.\-]*){0,3})"
)
ISO_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
QTY_RE = re.compile(
    r"\b(\d{1,4})\s*[- ]?\s*(?:seats?|users?|people|persons?|member|licen[cs]es?|qty|units?|pcs|pax)\b",
    re.IGNORECASE,
)
NUMBER_RE = re.compile(r"\b\d{1,7}(?:\.\d+)?\b")
AMOUNT_RE = re.compile(r"(?:rs\.?|inr|₹|\$|usd)\s*([\d,]+(?:\.\d+)?)", re.IGNORECASE)
PLAN_RE = re.compile(r"\b(starter|pro|growth|enterprise|basic|premium)\b(?:\s+(?:plan|tier|seats?))?", re.IGNORECASE)

FREE_MAIL_DOMAINS = {
    "gmail.com", "yahoo.com", "yahoo.in", "outlook.com", "hotmail.com",
    "icloud.com", "protonmail.com", "rediffmail.com", "live.com", "aol.com",
}

POSITIVE_CUES = (
    "payment done", "paid", "payment initiated", "payment going out",
    "payment will be processed", "signed up", "confirmed", "completed",
    "received", "done", "yes", "processed", "purchase", "bought",
)
NEGATIVE_CUES = (
    "not paid", "unpaid", "pending", "haven't received", "not received",
    "not working", "no,", "not yet", "awaiting",
)

# Trailing words that are part of the sentence, not the company name.
_COMPANY_STOPWORDS = {
    "I", "We", "Our", "Your", "The", "Please", "Can", "Could", "Is", "It",
    "Do", "Does", "Thanks", "Regards", "Also", "And",
}


def normalize_phone(raw):
    """Normalize a phone string to +<digits>; assume Indian numbers for 10-digit locals."""
    if not raw:
        return None
    digits = re.sub(r"[^\d]", "", str(raw))
    if len(digits) == 10:
        digits = "91" + digits
    if len(digits) < 10 or len(digits) > 15:
        return None
    return "+" + digits


def _guess_company(body, email):
    match = COMPANY_RE.search(body or "")
    if match:
        words = match.group(1).split()
        while words and words[0] in _COMPANY_STOPWORDS:
            words.pop(0)
        while words and words[-1] in _COMPANY_STOPWORDS:
            words.pop()
        if words:
            return " ".join(words).rstrip(".,")
    if email and "@" in email:
        domain = email.split("@", 1)[1].lower()
        if domain not in FREE_MAIL_DOMAINS:
            base = domain.split(".")[0]
            if base:
                return base.capitalize()
    return None


def _clean_company(value):
    """Tidy company strings coming from heuristics or the LLM
    (e.g. 'Zenlytics. Saw' -> 'Zenlytics')."""
    if not isinstance(value, str):
        return None
    value = value.split("\n")[0].split(".")[0].split(",")[0].strip()
    words = value.split()
    while words and words[-1] in _COMPANY_STOPWORDS:
        words.pop()
    value = " ".join(words)
    return value or None


def _sender_name(context):
    """The human counterparty: the sender, or the chat name for our own
    outbound messages ('Me')."""
    sender = (context.get("sender_name") or "").strip()
    if sender and sender.lower() != "me":
        return sender
    chat_name = (context.get("chat_name") or "").strip()
    return chat_name or None


def _stable_id(col_name, context):
    """Deterministic id for *_id text columns, derived from the counterparty
    phone (so all their messages hit the same row) with the message id as
    fallback. E.g. order_id -> 'ORD-5678'."""
    prefix = re.sub(r"[^a-z]", "", col_name.lower().replace("id", ""))[:3].upper() or "ROW"
    phone = re.sub(r"[^\d]", "", str(context.get("phone") or ""))
    if phone:
        return f"{prefix}-{phone[-4:]}"
    external_id = str(context.get("external_id") or "")
    if external_id:
        return f"{prefix}-{external_id[-6:]}"
    return None


def _found_email(body, context):
    if context.get("email"):
        return context["email"]
    m = EMAIL_RE.search(body or "")
    return m.group(0) if m else None


def _found_phone(body, context):
    phone = normalize_phone(context.get("phone"))
    if phone:
        return phone
    stripped = EMAIL_RE.sub(" ", body or "")  # avoid matching email digits
    m = PHONE_RE.search(stripped)
    return normalize_phone(m.group(0)) if m else None


def _extract_text(col, body, context):
    name = (col.get("name") or "").lower()
    if "phone" in name or "mobile" in name:
        return _found_phone(body, context)
    if "email" in name or "mail" in name:
        return _found_email(body, context)
    if name.endswith("id") and len(name) > 2:
        return _stable_id(col.get("name") or "", context)
    if "company" in name or "org" in name or "vendor" in name or "account" in name:
        return _clean_company(_guess_company(body, _found_email(body, context)))
    if "subject" in name or "topic" in name:
        return (context.get("subject") or "").strip() or None
    if any(k in name for k in ("item", "product", "plan", "sku", "package", "tier")):
        m = PLAN_RE.search(body or "")
        return f"{m.group(1).lower()} plan" if m else None
    if "source" in name or "channel" in name or "hint" in name:
        src = context.get("source")
        chat = context.get("chat_name") or context.get("subject")
        return f"{src}: {chat}" if src and chat else (src or None)
    if any(k in name for k in ("name", "person", "customer", "sender", "contact", "buyer", "lead", "who")):
        return _sender_name(context)
    # Generic text: a short snippet is better than nothing only for
    # description-ish columns; otherwise stay null.
    if any(k in name for k in ("note", "detail", "summary", "message", "body", "request", "description")):
        snippet = (body or "").strip().replace("\n", " ")
        return (snippet[:117] + "…") if len(snippet) > 120 else (snippet or None)
    return None


def _extract_number(col, body, context):
    name = (col.get("name") or "").lower()
    text = body or ""
    if any(k in name for k in ("amount", "price", "cost", "total", "value")):
        m = AMOUNT_RE.search(text)
        if m:
            return float(m.group(1).replace(",", ""))
    m = QTY_RE.search(text)
    if m:
        return int(m.group(1))
    # Avoid phone numbers / emails polluting the generic number match.
    stripped = EMAIL_RE.sub(" ", text)
    stripped = PHONE_RE.sub(" ", stripped)
    m = NUMBER_RE.search(stripped)
    if m:
        raw = m.group(0)
        return float(raw) if "." in raw else int(raw)
    return None


def _extract_date(col, body, context):
    m = ISO_DATE_RE.search(body or "")
    if m:
        return m.group(1)
    ts = str(context.get("ts") or "")
    return ts[:10] if ISO_DATE_RE.match(ts[:10] or "") else None


def _extract_bool(col, body, context):
    lowered = (body or "").lower()
    name = (col.get("name") or "").lower().replace("_", " ")
    if any(cue in lowered for cue in NEGATIVE_CUES):
        return False
    if any(cue in lowered for cue in POSITIVE_CUES):
        return True
    if name and name in lowered:  # bare mention of the concept, e.g. "paid"
        return True
    return None


def _extract_enum(col, body, context):
    lowered = (body or "").lower() + " " + str(context.get("subject") or "").lower()
    for option in col.get("options") or []:
        if str(option).lower() in lowered:
            return option
    return None


def heuristic_extract_typed(body, columns, context=None):
    """Mock/heuristic extraction: {column_name: typed value | None}."""
    context = context or {}
    out = {}
    for col in columns or []:
        if not isinstance(col, dict) or not col.get("name"):
            continue
        ctype = col.get("type")
        if ctype == "number":
            value = _extract_number(col, body, context)
        elif ctype == "date":
            value = _extract_date(col, body, context)
        elif ctype == "bool":
            value = _extract_bool(col, body, context)
        elif ctype == "enum":
            value = _extract_enum(col, body, context)
        else:  # text
            value = _extract_text(col, body, context)
        out[col["name"]] = value
    return out


def coerce_value(value, col):
    """Coerce an extracted value to its column type; None if impossible."""
    if value is None or value == "":
        return None
    ctype = col.get("type")
    try:
        if ctype == "number":
            if isinstance(value, bool):
                return None
            if isinstance(value, (int, float)):
                return value
            raw = str(value).replace(",", "").strip()
            return float(raw) if "." in raw else int(raw)
        if ctype == "bool":
            if isinstance(value, bool):
                return value
            lowered = str(value).strip().lower()
            if lowered in ("true", "yes", "y", "1", "paid", "done"):
                return True
            if lowered in ("false", "no", "n", "0", "unpaid", "pending"):
                return False
            return None
        if ctype == "date":
            m = ISO_DATE_RE.search(str(value))
            return m.group(1) if m else None
        if ctype == "enum":
            options = col.get("options") or []
            for option in options:
                if str(option).lower() == str(value).strip().lower():
                    return option
            return None
        return str(value).strip() or None
    except (TypeError, ValueError):
        return None


def extract(body, columns, context=None):
    """Extract typed values for `columns` from a message. Returns
    {column_name: value | None} with values coerced to column types."""
    context = context or {}
    columns = [c for c in (columns or []) if isinstance(c, dict) and c.get("name")]
    result = {}
    try:
        from agentcore.hermes_client import get_client  # lazy: agentcore may not exist yet

        client_result = get_client().extract(body or "", columns, context)
        if isinstance(client_result, dict):
            result = dict(client_result)
    except Exception:
        result = {}

    fallback = heuristic_extract_typed(body, columns, context)
    out = {}
    for col in columns:
        name = col["name"]
        value = coerce_value(result.get(name), col)
        if value is None:
            value = coerce_value(fallback.get(name), col)
        out[name] = value
    return out
