"""Field extraction from message bodies.

Uses agentcore.hermes_client.get_client().extract when available (lazy
import so pipelines works standalone); any missing fields are filled by
local heuristics: regex phone/email, name from sender_name, company from
email domain or "at <X>" phrasing, intent from keywords.
"""

import re

PHONE_RE = re.compile(r"(?:\+?\d[\d\-\s()]{7,}\d)")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
COMPANY_RE = re.compile(
    r"\b(?:at|from|with)\s+([A-Z][A-Za-z0-9&.\-]*(?:\s+[A-Z][A-Za-z0-9&.\-]*){0,3})"
)

FREE_MAIL_DOMAINS = {
    "gmail.com", "yahoo.com", "yahoo.in", "outlook.com", "hotmail.com",
    "icloud.com", "protonmail.com", "rediffmail.com", "live.com", "aol.com",
}

INTENT_KEYWORDS = [
    ("pricing", ["pricing", "price", "cost", "quote", "quotation", "how much", "plan"]),
    ("demo", ["demo", "walkthrough", "trial", "poc", "pilot", "show us", "showcase"]),
    ("buy", ["buy", "purchase", "order", "sign up", "signup", "subscribe", "onboard"]),
    ("support", ["support", "issue", "bug", "error", "not working", "broken", "help with", "problem"]),
    ("invoice", ["invoice", "payment", "billing", "gst", "receipt", "paid"]),
]

# Trailing words that are part of the sentence, not the company name.
_COMPANY_STOPWORDS = {
    "I", "We", "Our", "Your", "The", "Please", "Can", "Could", "Is", "It",
    "Do", "Does", "Thanks", "Regards", "Also", "And",
}


def normalize_phone(raw):
    """Normalize a phone string to +<digits>; assume Indian numbers for 10-digit locals."""
    if not raw:
        return None
    digits = re.sub(r"[^\d]", "", raw)
    if len(digits) == 10:
        digits = "91" + digits
    if len(digits) < 10 or len(digits) > 15:
        return None
    return "+" + digits


def _guess_intent(body: str):
    lowered = body.lower()
    for intent, keywords in INTENT_KEYWORDS:
        if any(k in lowered for k in keywords):
            return intent
    return None


def _guess_company(body: str, email):
    match = COMPANY_RE.search(body)
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


def _heuristic_extract(body, fields, sender_name=None, phone=None, email=None):
    body = body or ""
    result = {}

    found_email = email
    if not found_email:
        m = EMAIL_RE.search(body)
        found_email = m.group(0) if m else None

    found_phone = normalize_phone(phone)
    if not found_phone:
        # Avoid matching the email's local part digits: strip emails first.
        stripped = EMAIL_RE.sub(" ", body)
        m = PHONE_RE.search(stripped)
        found_phone = normalize_phone(m.group(0)) if m else None

    for field in fields:
        if field == "name":
            result[field] = sender_name or None
        elif field == "phone":
            result[field] = found_phone
        elif field == "email":
            result[field] = found_email
        elif field == "company":
            result[field] = _guess_company(body, found_email)
        elif field == "intent":
            result[field] = _guess_intent(body)
        else:
            result[field] = None
    return result


def _clean_company(value):
    """Tidy company strings coming from body heuristics or the LLM/mock
    (e.g. 'Zenlytics. Saw' -> 'Zenlytics')."""
    if not isinstance(value, str):
        return None
    value = value.split("\n")[0].split(".")[0].split(",")[0].strip()
    words = value.split()
    while words and words[-1] in _COMPANY_STOPWORDS:
        words.pop()
    value = " ".join(words)
    return value or None


def extract(body, fields, sender_name=None, phone=None, email=None):
    """Extract `fields` from a message. Returns {field: value|None}."""
    result = {}
    try:
        from agentcore.hermes_client import get_client  # lazy: agentcore may not exist yet

        client_result = get_client().extract(body or "", list(fields))
        if isinstance(client_result, dict):
            result = {k: v for k, v in client_result.items() if k in fields}
    except Exception:
        result = {}

    fallback = _heuristic_extract(
        body, fields, sender_name=sender_name, phone=phone, email=email
    )
    for field in fields:
        if result.get(field) in (None, ""):
            result[field] = fallback.get(field)
    # Source metadata is more reliable than body guesses.
    if "name" in fields and sender_name and sender_name.strip().lower() != "me":
        result["name"] = sender_name.strip()
    if "phone" in result:
        result["phone"] = normalize_phone(result["phone"])
    if "company" in result:
        result["company"] = _clean_company(result["company"])
    return result
