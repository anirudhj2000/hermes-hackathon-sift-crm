"""Hermes client per CONTRACTS.md.

get_client() returns HermesClient (real, OpenAI-compatible against
HERMES_BASE_URL) when HERMES_API_KEY is set, else MockHermesClient.

Both expose:
  chat(messages, tools) -> iterator of
      {"type": "text", "text": str} | {"type": "tool_call", "name": str, "args": dict}
  extract(body, columns, context) -> dict   (v2: typed against table columns)
  filter_relevant(bodies, instruction) -> list[bool]
"""

import json
import os
import re

DEFAULT_BASE_URL = "https://inference.nousresearch.com/v1"
DEFAULT_MODEL = "Hermes-4-405B"

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

def heuristic_extract(body, columns, context=None):
    """Typed per-column heuristics (v2) — shared with the pipeline extractor."""
    try:
        from pipelines.extractor import heuristic_extract_typed

        return heuristic_extract_typed(body, columns, context or {})
    except Exception:
        return {c.get("name"): None for c in (columns or []) if isinstance(c, dict)}


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
            stream_options={"include_usage": True},
        )
        pending = {}  # index -> accumulating tool call
        usage = None
        for chunk in stream:
            # The final usage chunk (include_usage) carries no choices.
            if getattr(chunk, "usage", None):
                usage = chunk.usage
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
        if usage is not None:
            yield {
                "type": "usage",
                "input_tokens": getattr(usage, "prompt_tokens", None),
                "output_tokens": getattr(usage, "completion_tokens", None),
            }
        for _, slot in sorted(pending.items()):
            try:
                args = json.loads(slot["args"] or "{}")
            except (ValueError, TypeError):
                args = {}
            yield {"type": "tool_call", "name": slot["name"], "args": args, "id": slot["id"]}

    def extract(self, body, columns, context=None):
        """One structured-output call typed against the table columns
        (name/type/description/options). Falls back to heuristics."""
        context = context or {}
        spec = [
            {
                "name": c.get("name"),
                "type": c.get("type"),
                "description": c.get("description", ""),
                **({"options": c["options"]} if c.get("options") else {}),
            }
            for c in (columns or [])
            if isinstance(c, dict) and c.get("name")
        ]
        names = [c["name"] for c in spec]
        prompt = (
            "Extract a typed row from the message below.\n"
            "Respond with ONLY a JSON object whose keys are exactly the column "
            "names; use null for anything not present. Respect each column's "
            "type (number, date as YYYY-MM-DD, bool, enum must be one of the "
            "options, otherwise text).\n"
            f"Columns: {json.dumps(spec)}\n"
            f"Message metadata: {json.dumps({k: v for k, v in context.items() if v})}\n"
            f"Message:\n{body}"
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
            return {name: data.get(name) for name in names}
        except Exception:
            return heuristic_extract(body, columns, context)

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
# Mock client — scripted, demo-worthy transcript (CONTRACTS v2)
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


def _col(name, ctype, description, options=None):
    col = {"name": name, "type": ctype, "description": description}
    if options:
        col["options"] = options
    return col


# Keyword-triggered table designs: (keywords, table name, columns,
# dedupe_keys, filter instruction). First match wins; leads is the default.
TABLE_PRESETS = [
    (
        ("order", "purchase", "bought", "buying"),
        "Orders",
        [
            _col("order_id", "text", "Stable order reference per buyer"),
            _col("customer", "text", "Who placed or asked about the order"),
            _col("item", "text", "Product or plan being ordered"),
            _col("qty", "number", "Quantity — seats, users, or units"),
            _col("paid", "bool", "Whether payment is confirmed"),
        ],
        ["order_id"],
        "keep messages that mention an order, purchase, payment, or invoice",
    ),
    (
        ("invoice", "billing", "receipt"),
        "Invoices",
        [
            _col("invoice_id", "text", "Stable invoice reference per customer"),
            _col("customer", "text", "Billed customer"),
            _col("company", "text", "Customer's company"),
            _col("amount", "number", "Invoice amount if mentioned"),
            _col("paid", "bool", "Whether payment is confirmed"),
        ],
        ["invoice_id"],
        "keep messages about an invoice, billing, or payment",
    ),
    (
        ("support", "issue", "bug", "complaint", "ticket"),
        "Support Tickets",
        [
            _col("ticket_id", "text", "Stable ticket reference per reporter"),
            _col("customer", "text", "Who reported the issue"),
            _col("summary", "text", "Short description of the issue"),
            _col("resolved", "bool", "Whether it was fixed"),
        ],
        ["ticket_id"],
        "keep messages about an issue, bug, error, or something not working",
    ),
    (
        (),  # default: leads / pricing interest
        "Leads",
        [
            _col("person", "text", "Lead's name"),
            _col("company", "text", "Lead's company"),
            _col(
                "intent", "enum", "What they want",
                options=["pricing", "demo", "trial", "purchase", "partnership"],
            ),
            _col("phone", "text", "Contact phone if present"),
        ],
        ["person"],
        "keep messages that ask about pricing, a demo, a trial, or buying",
    ),
]

QUESTION_RE = re.compile(
    r"\bwhat tables\b|\bwhich tables\b|\blist (?:my )?tables\b|\bhow many rows\b"
)


class MockHermesClient:
    """Scripted tool-calling chat. Stateless: the current stage is derived
    from the tool-result messages already present in `messages`, so the
    standard chat loop (execute tool -> append result -> call chat again)
    just works.

    v2 script: narrate a plan -> create_table (typed schema + dedupe key)
    -> create_workflow (v2 DSL targeting the slug the create_table tool
    RETURNED) -> run_workflow -> closing summary."""

    def chat(self, messages, tools):
        user_msg = next(
            (m.get("content") or "" for m in messages if m.get("role") == "user"), ""
        )
        results = self._tool_results(messages)

        # Q&A path: "What tables do I have, and how many rows in each?"
        if QUESTION_RE.search(user_msg.lower()):
            if results["tables_listing"] is None:
                yield from self._say("Let me check your workspace...")
                yield {"type": "tool_call", "name": "list_tables", "args": {}}
            else:
                yield from self._say(self._tables_answer(results["tables_listing"]))
            return

        plan = self._plan(user_msg)

        # Stage 1: design the table schema.
        if not results["tables"]:
            yield from self._say(self._opening_narration(plan))
            yield {
                "type": "tool_call",
                "name": "create_table",
                "args": {
                    "name": plan["table_name"],
                    "columns": plan["columns"],
                    "dedupe_keys": plan["dedupe_keys"],
                },
            }
            return

        table = results["tables"][-1]
        slug = table.get("slug")

        # Stage 2: build the pipeline against the slug the tool returned.
        if not results["workflows"]:
            yield from self._say(
                f'\n\nTable "{table.get("name", slug)}" is ready (slug {slug}). '
                "Now building the pipeline that fills it..."
            )
            yield {
                "type": "tool_call",
                "name": "create_workflow",
                "args": {
                    "name": self._workflow_name(plan),
                    "dsl": self._build_dsl(slug, plan),
                },
            }
            return

        workflow = results["workflows"][-1]

        # Stage 3: kick off the first run.
        if not results["runs"]:
            yield from self._say(
                f'\n\nWorkflow "{workflow.get("name", "workflow")}" is saved '
                f"(id {workflow.get('workflow_id')}). Starting the first run now..."
            )
            yield {
                "type": "tool_call",
                "name": "run_workflow",
                "args": {"workflow_id": workflow.get("workflow_id")},
            }
            return

        # Final stage: closing summary, no more tool calls.
        yield from self._say(self._closing_summary(plan, table, workflow, results["runs"][-1]))

    def extract(self, body, columns, context=None):
        return heuristic_extract(body, columns, context)

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
        """Bucket prior tool results by shape: created tables, created
        workflows, started runs, list_tables output."""
        out = {"tables": [], "workflows": [], "runs": [], "tables_listing": None}
        for m in messages:
            if m.get("role") != "tool":
                continue
            try:
                data = json.loads(m.get("content") or "{}")
            except (ValueError, TypeError):
                continue
            if not isinstance(data, dict) or data.get("error"):
                continue
            if "table_id" in data:
                out["tables"].append(data)
            elif "workflow_id" in data:
                out["workflows"].append(data)
            elif "run_id" in data:
                out["runs"].append(data)
            elif "tables" in data:
                out["tables_listing"] = data
        return out

    @staticmethod
    def _plan(user_msg):
        lower = user_msg.lower()
        available = _registry_sources()  # only sources declared in the registry
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
            since_days = 14  # generous default so fixture history is covered

        # Interval trigger: "every 30 minutes", "every 2 hours", "keep it updated".
        trigger = "manual"
        m = re.search(r"every\s+(\d+)\s*(minutes?|mins?|hours?|hrs?)", lower)
        if m:
            minutes = int(m.group(1)) * (60 if m.group(2).startswith(("hour", "hr")) else 1)
            trigger = {"type": "interval", "minutes": max(1, minutes)}
        elif re.search(r"keep (?:it |this |them )?(?:updated|up to date|updating|fresh)|periodically|continuously", lower):
            trigger = {"type": "interval", "minutes": 30}

        keywords_hit = None
        for keywords, table_name, columns, dedupe_keys, filter_instruction in TABLE_PRESETS:
            if not keywords or any(k in lower for k in keywords):
                keywords_hit = (table_name, columns, dedupe_keys, filter_instruction)
                break
        table_name, columns, dedupe_keys, filter_instruction = keywords_hit

        return {
            "sources": sources,
            "since_days": since_days,
            "trigger": trigger,
            "table_name": table_name,
            "columns": columns,
            "dedupe_keys": dedupe_keys,
            "filter_instruction": filter_instruction,
        }

    @staticmethod
    def _workflow_name(plan):
        labels = " + ".join(SOURCE_LABELS[s] for s in plan["sources"])
        return f"{plan['table_name']} — {labels} sync ({plan['since_days']}d)"

    @staticmethod
    def _build_dsl(table_slug, plan):
        steps = []
        for source in plan["sources"]:
            steps.append({"type": "fetch", "source": source, "since_days": plan["since_days"]})
        steps.append({"type": "filter", "instruction": plan["filter_instruction"]})
        steps.append({"type": "extract"})
        steps.append({"type": "upsert", "dedupe_on": plan["dedupe_keys"]})
        return {
            "name": MockHermesClient._workflow_name(plan),
            "trigger": plan["trigger"],
            "table": table_slug,
            "steps": steps,
        }

    @staticmethod
    def _trigger_phrase(trigger):
        if isinstance(trigger, dict):
            minutes = trigger.get("minutes", 30)
            if minutes % 60 == 0 and minutes >= 60:
                hours = minutes // 60
                return f"re-run automatically every {hours} hour{'s' if hours > 1 else ''}"
            return f"re-run automatically every {minutes} minutes"
        return "run on demand"

    @staticmethod
    def _opening_narration(plan):
        labels = [SOURCE_LABELS[s] for s in plan["sources"]]
        src_text = " and ".join(labels)
        col_bits = ", ".join(
            f"{c['name']} ({c['type']})" for c in plan["columns"]
        )
        key_text = ", ".join(plan["dedupe_keys"]) or "none — every message becomes a row"
        return (
            f"Got it. I'll design a \"{plan['table_name']}\" table and sift your "
            f"{src_text} messages from the last {plan['since_days']} days into it.\n\n"
            f"Schema: {col_bits}. Rows merge on {key_text}, so repeat messages "
            "update the same row instead of duplicating it. The pipeline will "
            f"{MockHermesClient._trigger_phrase(plan['trigger'])}.\n\n"
            "Creating the table first..."
        )

    @staticmethod
    def _closing_summary(plan, table, workflow, run):
        schedule = MockHermesClient._trigger_phrase(plan["trigger"])
        return (
            "\n\nAll set! Here's what I did:\n"
            f"- Designed the \"{table.get('name')}\" table ({table.get('slug')}) "
            f"with {len(table.get('columns') or [])} typed columns.\n"
            f"- Created workflow \"{workflow.get('name')}\" (id {workflow.get('workflow_id')}) "
            f"targeting it — it will {schedule}.\n"
            f"- Started run #{run.get('run_id')}, which is processing in the background.\n\n"
            "Watch the table fill up on the Tables page — each row carries "
            "provenance back to the exact source messages."
        )

    @staticmethod
    def _tables_answer(listing):
        tables = listing.get("tables") or []
        if not tables:
            return (
                "You don't have any tables yet. Tell me what you want to track "
                "— e.g. \"track orders from my WhatsApp chats\" — and I'll design one."
            )
        lines = [f"You have {len(tables)} table{'s' if len(tables) != 1 else ''}:"]
        for t in tables:
            cols = ", ".join(c.get("name", "?") for c in t.get("columns") or [])
            rows = t.get("record_count", 0)
            lines.append(f"\n- {t.get('name')} ({t.get('slug')}): {rows} rows — columns: {cols}")
        return "".join(lines)
