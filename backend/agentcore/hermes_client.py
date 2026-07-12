"""Hermes client per CONTRACTS.md.

get_client() returns HermesClient (real, OpenAI-compatible against
HERMES_BASE_URL) when HERMES_API_KEY is set, else MockHermesClient.

Both expose:
  chat(messages, tools) -> iterator of
      {"type": "text", "text": str} | {"type": "tool_call", "name": str, "args": dict}
  extract(body, fields) -> dict
  filter_relevant(bodies, instruction) -> list[bool]
"""

import json
import os
import re

DEFAULT_BASE_URL = "https://inference.nousresearch.com/v1"
DEFAULT_MODEL = "Hermes-4-405B"

PHONE_RE = re.compile(r"\+?\d[\d\s().-]{7,}\d")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
STOPWORDS = {
    "the", "and", "that", "with", "for", "from", "keep", "only", "messages",
    "message", "about", "which", "are", "ask", "asking", "mention", "mentions",
    "mentioning", "contain", "containing", "relate", "related", "relevant",
}


def get_client():
    if os.environ.get("HERMES_API_KEY"):
        return HermesClient()
    return MockHermesClient()


# ---------------------------------------------------------------------------
# Shared heuristics (used by the mock, and as fallback by the real client)
# ---------------------------------------------------------------------------

INTENT_KEYWORDS = [
    ("pricing", ["pricing", "price", "cost", "quote", "how much", "plan"]),
    ("demo", ["demo", "walkthrough", "trial"]),
    ("support", ["support", "issue", "problem", "help", "broken", "bug"]),
    ("sales", ["buy", "purchase", "interested", "sign up", "upgrade"]),
]


def heuristic_extract(body, fields):
    out = {}
    text = body or ""
    lower = text.lower()
    for field in fields:
        f = field.lower()
        if f == "phone":
            m = PHONE_RE.search(text)
            out[field] = re.sub(r"[\s().-]", "", m.group(0)) if m else None
        elif f == "email":
            m = EMAIL_RE.search(text)
            out[field] = m.group(0) if m else None
        elif f == "intent":
            out[field] = next(
                (name for name, kws in INTENT_KEYWORDS if any(k in lower for k in kws)),
                None,
            )
        elif f == "name":
            m = re.search(
                r"(?:my name is|this is|i am|i'm)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
                text,
                re.IGNORECASE,
            )
            out[field] = m.group(1).title() if m else None
        elif f == "company":
            m = re.search(
                r"(?:from|at|with)\s+([A-Z][A-Za-z0-9&.]+(?:\s+[A-Z][A-Za-z0-9&.]+)?)",
                text,
            )
            out[field] = m.group(1) if m else None
        else:
            out[field] = None
    return out


def heuristic_filter(bodies, instruction):
    tokens = [
        w for w in re.findall(r"[a-z0-9']+", (instruction or "").lower())
        if len(w) > 3 and w not in STOPWORDS
    ]
    if not tokens:
        return [True] * len(bodies)
    return [any(t in (b or "").lower() for t in tokens) for b in bodies]


# ---------------------------------------------------------------------------
# Real client
# ---------------------------------------------------------------------------

class HermesClient:
    def __init__(self):
        from openai import OpenAI

        self._client = OpenAI(
            api_key=os.environ["HERMES_API_KEY"],
            base_url=os.environ.get("HERMES_BASE_URL", DEFAULT_BASE_URL),
        )
        self.model = os.environ.get("HERMES_MODEL", DEFAULT_MODEL)

    def chat(self, messages, tools):
        stream = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools or None,
            stream=True,
        )
        pending = {}  # index -> accumulating tool call
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                yield {"type": "text", "text": delta.content}
            for tc in delta.tool_calls or []:
                slot = pending.setdefault(tc.index, {"id": "", "name": "", "args": ""})
                if tc.id:
                    slot["id"] = tc.id
                if tc.function:
                    if tc.function.name:
                        slot["name"] += tc.function.name
                    if tc.function.arguments:
                        slot["args"] += tc.function.arguments
        for _, slot in sorted(pending.items()):
            try:
                args = json.loads(slot["args"] or "{}")
            except (ValueError, TypeError):
                args = {}
            yield {"type": "tool_call", "name": slot["name"], "args": args, "id": slot["id"]}

    def extract(self, body, fields):
        prompt = (
            "Extract the following fields from the message below. "
            "Respond with ONLY a JSON object whose keys are exactly the field names; "
            "use null for anything not present.\n"
            f"Fields: {json.dumps(fields)}\nMessage:\n{body}"
        )
        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
            )
            text = resp.choices[0].message.content or ""
            m = re.search(r"\{.*\}", text, re.DOTALL)
            data = json.loads(m.group(0)) if m else {}
            return {f: data.get(f) for f in fields}
        except Exception:
            return heuristic_extract(body, fields)

    def filter_relevant(self, bodies, instruction):
        prompt = (
            "For each numbered message below, answer whether it matches this "
            f"instruction: {instruction!r}. Respond with ONLY a JSON array of booleans, "
            "one per message, in order.\n"
            + "\n".join(f"{i + 1}. {b}" for i, b in enumerate(bodies))
        )
        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
            )
            text = resp.choices[0].message.content or ""
            m = re.search(r"\[.*\]", text, re.DOTALL)
            data = json.loads(m.group(0)) if m else []
            if len(data) == len(bodies):
                return [bool(x) for x in data]
        except Exception:
            pass
        return heuristic_filter(bodies, instruction)


# ---------------------------------------------------------------------------
# Mock client — scripted, demo-worthy transcript
# ---------------------------------------------------------------------------

SOURCE_LABELS = {"whatsapp": "WhatsApp", "gmail": "Gmail"}


def _registry_sources():
    """Connector names from the agent workspace registry; falls back to the
    pinned pair so mock mode keeps working if the workspace is missing."""
    try:
        from .workspace import get_valid_sources

        sources = get_valid_sources()
        if sources:
            return sources
    except Exception:
        pass
    return {"whatsapp", "gmail"}


class MockHermesClient:
    """Scripted tool-calling chat. Stateless: the current stage is derived
    from the tool-result messages already present in `messages`, so the
    standard chat loop (execute tool -> append result -> call chat again)
    just works."""

    def chat(self, messages, tools):
        user_msg = next(
            (m.get("content") or "" for m in messages if m.get("role") == "user"), ""
        )
        plan = self._plan(user_msg)
        sources = plan["sources"]

        created, runs = self._tool_results(messages)

        # Stage 1..n: narrate (first time) and create one workflow per source.
        if len(created) < len(sources):
            idx = len(created)
            source = sources[idx]
            if idx == 0:
                yield from self._say(self._opening_narration(plan))
            else:
                yield from self._say(
                    f"\n\n{SOURCE_LABELS[source]} workflow next — same shape, "
                    f"but fetching from {SOURCE_LABELS[source]} instead."
                )
            yield {
                "type": "tool_call",
                "name": "create_workflow",
                "args": {
                    "name": self._workflow_name(source, plan),
                    "dsl": self._build_dsl(source, plan),
                },
            }
            return

        # Stage n+1..2n: kick off a run for each created workflow.
        if len(runs) < len(created):
            target = created[len(runs)]
            yield from self._say(
                f"\n\nWorkflow \"{target.get('name', 'workflow')}\" is saved "
                f"(id {target.get('workflow_id')}). Starting it now..."
            )
            yield {
                "type": "tool_call",
                "name": "run_workflow",
                "args": {"workflow_id": target.get("workflow_id")},
            }
            return

        # Final stage: closing summary, no more tool calls.
        yield from self._say(self._closing_summary(plan, created, runs))

    def extract(self, body, fields):
        return heuristic_extract(body, fields)

    def filter_relevant(self, bodies, instruction):
        return heuristic_filter(bodies, instruction)

    # -- internals ----------------------------------------------------------

    @staticmethod
    def _say(text):
        """Yield text in small chunks so the UI visibly streams."""
        words = text.split(" ")
        for i in range(0, len(words), 4):
            chunk = " ".join(words[i:i + 4])
            if i + 4 < len(words):
                chunk += " "
            yield {"type": "text", "text": chunk}

    @staticmethod
    def _tool_results(messages):
        """Split prior tool results into workflow-creation results and run results."""
        created, runs = [], []
        for m in messages:
            if m.get("role") != "tool":
                continue
            try:
                data = json.loads(m.get("content") or "{}")
            except (ValueError, TypeError):
                continue
            if "run_id" in data:
                runs.append(data)
            elif "workflow_id" in data:
                created.append(data)
        return created, runs

    @staticmethod
    def _plan(user_msg):
        lower = user_msg.lower()
        available = _registry_sources()  # only sources declared in the workspace registry
        sources = []
        if "whatsapp" in lower and "whatsapp" in available:
            sources.append("whatsapp")
        if ("gmail" in lower or "email" in lower or "mail" in lower) and "gmail" in available:
            sources.append("gmail")
        if not sources:
            sources = ["whatsapp"] if "whatsapp" in available else sorted(available)[:1] or ["whatsapp"]

        m = re.search(r"last\s+(\d+)\s+days?", lower)
        if m:
            since_days = int(m.group(1))
        elif "last month" in lower or "past month" in lower or "30 days" in lower:
            since_days = 30
        else:
            since_days = 7  # "last week" / default

        tag = None
        m = re.search(r"tag(?:ging)?\s+(?:the\s+)?([a-z][a-z0-9 -]*?)\s+(?:leads?|contacts?)", lower)
        if m:
            tag = m.group(1).strip().replace(" ", "-")
        else:
            for name, kws in INTENT_KEYWORDS:
                if any(k in lower for k in kws):
                    tag = f"{name}-lead"  # e.g. "pricing-lead" (matches the demo script)
                    break
        return {"sources": sources, "since_days": since_days, "tag": tag}

    @staticmethod
    def _topic(plan):
        """Human-readable topic word for a tag, e.g. 'pricing' for 'pricing-lead'."""
        tag = plan["tag"] or ""
        return tag.removesuffix("-lead") or tag

    @staticmethod
    def _workflow_name(source, plan):
        base = f"{SOURCE_LABELS[source]} import ({plan['since_days']}d)"
        if plan["tag"]:
            topic = MockHermesClient._topic(plan)
            base = f"{SOURCE_LABELS[source]} {topic} leads ({plan['since_days']}d)"
        return base

    @staticmethod
    def _build_dsl(source, plan):
        steps = [{"type": "fetch", "source": source, "since_days": plan["since_days"]}]
        if plan["tag"]:
            topic = MockHermesClient._topic(plan)
            steps.append({
                "type": "filter",
                "instruction": f"keep messages that mention {topic} or ask about it",
            })
        steps.append({
            "type": "extract",
            "fields": ["name", "phone", "email", "company", "intent"],
        })
        steps.append({
            "type": "upsert",
            "dedupe_on": ["phone", "email"],
            "tag": plan["tag"],
        })
        return {
            "name": MockHermesClient._workflow_name(source, plan),
            "trigger": "manual",
            "steps": steps,
        }

    @staticmethod
    def _opening_narration(plan):
        labels = [SOURCE_LABELS[s] for s in plan["sources"]]
        src_text = " and ".join(labels)
        parts = [
            f"Got it. I'll create a workflow that fetches your {src_text} "
            f"messages from the last {plan['since_days']} days, extracts contact "
            "details (name, phone, email, company) and intent from each message,"
        ]
        if plan["tag"]:
            parts.append(
                f" filters for {MockHermesClient._topic(plan)}-related conversations, and creates "
                f"contacts tagged \"{plan['tag']}\" — deduplicated on phone and email."
            )
        else:
            parts.append(
                " and creates contacts deduplicated on phone and email."
            )
        if len(plan["sources"]) > 1:
            parts.append(
                f" Since you mentioned both {labels[0]} and {labels[1]}, "
                "I'll set up one workflow per source."
            )
        parts.append(f"\n\nCreating the {labels[0]} workflow first...")
        return "".join(parts)

    @staticmethod
    def _closing_summary(plan, created, runs):
        lines = ["\n\nAll set! Here's what I did:"]
        for wf, run in zip(created, runs):
            lines.append(
                f"\n- Created workflow \"{wf.get('name', '?')}\" "
                f"(id {wf.get('workflow_id')}) and started run #{run.get('run_id')}."
            )
        tag_note = (
            f" Matching contacts will be tagged \"{plan['tag']}\"." if plan["tag"] else ""
        )
        lines.append(
            "\n\nThe runs are processing in the background — watch the Runs page "
            f"for live progress.{tag_note} New contacts will appear in your CRM "
            "as each run finishes."
        )
        return "".join(lines)
