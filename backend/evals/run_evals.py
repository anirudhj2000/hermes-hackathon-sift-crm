"""Sift eval runner — two suites, scored on traces.

    python backend/evals/run_evals.py [system|skills|all]

Suite 1 (system prompt): replays each golden request through the real agent
loop (real SYSTEM_PROMPT, real client, real tool schemas) against an in-memory
dry tool layer — no DB writes, no disk, no background threads — then scores the
agent's decisions off the recorded tool calls + narration.

Suite 2 (skills): drives the pipeline's tool-level units directly (extractor,
filter, DSL validator, upsert engine) against hand-labeled expectations.

Runs fully offline against the mock client. When LANGFUSE_* keys are set, each
case is emitted as a Langfuse trace carrying its per-dimension scores and tagged
with git_sha + prompt_hash, so runs compare across versions. A JSON report is
always written to backend/evals/reports/.
"""

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BACKEND)
sys.path.insert(0, HERE)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django  # noqa: E402

django.setup()

import scorers  # noqa: E402
from agentcore import tools as tool_defs, tracing  # noqa: E402
from agentcore.hermes_client import get_client  # noqa: E402
from agentcore.views import MAX_TURNS, SYSTEM_PROMPT, _system_message  # noqa: E402

GOLDEN = os.path.join(HERE, "golden")
REPORTS = os.path.join(HERE, "reports")


def _load_jsonl(path):
    with open(path) as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _git_sha():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=BACKEND, stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        return "nogit"


PROMPT_HASH = hashlib.sha1(SYSTEM_PROMPT.encode()).hexdigest()[:8]
GIT_SHA = _git_sha()


# ---------------------------------------------------------------------------
# Dry tool layer — mirrors agentcore.tools contracts with zero side effects
# ---------------------------------------------------------------------------

class DryTools:
    def __init__(self, setup):
        self.calls = []
        self.setup = setup or {}
        self.tables = {}  # slug -> {name, columns, dedupe_keys, record_count}
        for t in self.setup.get("existing_tables", []):
            self.tables[t["slug"]] = {k: v for k, v in t.items() if k != "slug"}
        self.scoped = self.setup.get("scoped_chats", [])
        self._seq = 0

    def execute(self, name, args):
        result = self._dispatch(name, args or {})
        self.calls.append({"name": name, "args": args or {}, "result": result})
        return result

    def _dispatch(self, name, args):
        if name == "create_table":
            return self._create_table(args)
        if name == "list_tables":
            return {"tables": [{"slug": s, **t} for s, t in self.tables.items()]}
        if name == "query_records":
            return {"count": 0, "rows": []}
        if name == "list_sources":
            return {"sources": [
                {"source": "whatsapp", "status": "connected", "mode": "mock"},
                {"source": "gmail", "status": "connected", "mode": "mock"},
            ]}
        if name == "create_workflow":
            return self._create_workflow(args)
        if name == "run_workflow":
            self._seq += 1
            return {"run_id": self._seq}
        if name == "list_whatsapp_chats":
            return {"chats": self.scoped, "note": (
                "Only scoped chats are listed." if self.scoped
                else "No chats are scoped yet — ask the user to sync and scope chats on the WhatsApp page."
            )}
        if name in ("list_files", "read_file", "write_file"):
            return {"ok": True}
        return {"error": "unknown tool", "name": name}

    def _create_table(self, args):
        from django.utils.text import slugify
        from crm.serializers import validate_columns_spec, validate_dedupe_keys_spec

        name = args.get("name", "")
        cols = args.get("columns") or []
        keys = args.get("dedupe_keys") or []
        errs = list(validate_columns_spec(cols) or [])
        if not errs:
            errs.extend(validate_dedupe_keys_spec(keys, cols))
        if not str(name).strip():
            errs.append("'name' must be a non-empty string")
        if errs:
            return {"error": "invalid table", "details": errs}
        base = slugify(name)[:240] or "table"
        slug, i = base, 2
        while slug in self.tables:
            slug, i = f"{base}-{i}", i + 1
        self.tables[slug] = {"name": name.strip(), "columns": cols, "dedupe_keys": keys, "record_count": 0}
        return {"table_id": len(self.tables), "slug": slug, "name": name.strip(),
                "columns": cols, "dedupe_keys": keys}

    def _create_workflow(self, args):
        errs = self._validate_dsl(args.get("dsl") or {})
        if errs:
            return {"error": "invalid dsl", "details": errs}
        self._seq += 1
        return {"workflow_id": self._seq, "name": args.get("name", ""), "dsl": args.get("dsl")}

    def _validate_dsl(self, dsl):
        """Hermetic DSL check: reuses pure helpers, resolves the table slug
        against this run's in-memory tables instead of the DB."""
        from pipelines.dsl import VALID_STEP_TYPES, _registry_sources, validate_trigger

        errs = []
        if not isinstance(dsl, dict):
            return ["dsl must be an object"]
        if not (isinstance(dsl.get("name"), str) and dsl["name"].strip()):
            errs.append("'name' must be non-empty")
        errs.extend(validate_trigger(dsl.get("trigger")))
        slug = dsl.get("table")
        table = self.tables.get(slug) if isinstance(slug, str) else None
        if not (isinstance(slug, str) and slug.strip()):
            errs.append("'table' required")
        elif table is None:
            errs.append(f"no table {slug!r}")
        sources = _registry_sources()
        steps = dsl.get("steps")
        if not isinstance(steps, list) or not steps:
            return errs + ["'steps' must be non-empty"]
        seen = []
        for i, st in enumerate(steps):
            if not isinstance(st, dict) or st.get("type") not in VALID_STEP_TYPES:
                errs.append(f"steps[{i}] unknown type")
                continue
            seen.append(st["type"])
            if st["type"] == "fetch" and st.get("source") not in sources:
                errs.append(f"steps[{i}] fetch source must be a declared connector {sorted(sources)}")
            if st["type"] == "upsert" and isinstance(st.get("dedupe_on"), list) and table:
                names = {c.get("name") for c in table["columns"] if isinstance(c, dict)}
                for k in st["dedupe_on"]:
                    if k not in names:
                        errs.append(f"steps[{i}] dedupe key {k!r} not a column")
        for req in ("fetch", "extract", "upsert"):
            if req not in seen:
                errs.append(f"requires {req} step")
        return errs


def run_agent(message, setup):
    """Headless mirror of agentcore.views._stream against DryTools."""
    client = get_client()
    dry = DryTools(setup)
    messages = [
        {"role": "system", "content": _system_message()},
        {"role": "user", "content": message},
    ]
    texts = []
    for _ in range(MAX_TURNS):
        text_parts, tool_calls = [], []
        for ev in client.chat(messages, tool_defs.TOOL_SCHEMAS):
            if ev["type"] == "text":
                text_parts.append(ev["text"])
            elif ev["type"] == "tool_call":
                tool_calls.append(ev)
        texts.append("".join(text_parts))
        if not tool_calls:
            break
        assistant = {"role": "assistant", "content": "".join(text_parts) or None, "tool_calls": []}
        executed = []
        for call in tool_calls:
            cid = call.get("id") or f"call_{len(dry.calls)}"
            assistant["tool_calls"].append({
                "id": cid, "type": "function",
                "function": {"name": call["name"], "arguments": json.dumps(call["args"])},
            })
            executed.append((cid, call))
        messages.append(assistant)
        for cid, call in executed:
            result = dry.execute(call["name"], call["args"])
            messages.append({"role": "tool", "tool_call_id": cid, "content": json.dumps(result)})
    return {"calls": dry.calls, "text": "\n".join(t for t in texts if t).strip(),
            "created_slugs": set(dry.tables.keys())}


# ---------------------------------------------------------------------------
# Skill runners
# ---------------------------------------------------------------------------

def run_extraction(case):
    from pipelines.extractor import extract

    return extract(case["body"], case["columns"], case.get("context") or {})


def run_filter(case):
    return get_client().filter_relevant(case["bodies"], case["instruction"])


def run_dsl(case):
    from crm.models import DataTable
    from pipelines.dsl import validate_dsl

    table = DataTable.objects.create(
        name=f"__eval_{case['id']}", columns=case["table_columns"],
        dedupe_keys=case.get("table_dedupe") or [],
    )
    try:
        dsl = json.loads(json.dumps(case["dsl"]).replace("$TABLE", table.slug))
        return validate_dsl(dsl)
    finally:
        table.delete()


def run_upsert(case):
    from crm.models import DataTable
    from pipelines.engine import _upsert_record

    table = DataTable.objects.create(
        name=f"__eval_{case['id']}", columns=case["columns"],
        dedupe_keys=case.get("dedupe_keys") or [],
    )
    try:
        dedupe_on = list(table.dedupe_keys or [])
        stats = {"rows_created": 0, "rows_updated": 0}
        index, created_ids, updated_ids, input_ids = {}, set(), set(), set()
        for m in case["messages"]:
            input_ids.add(m.get("external_id", ""))
            msg = {"extracted": m["extracted"], "source": m.get("source", "whatsapp"),
                   "external_id": m.get("external_id", ""), "ts": m.get("ts")}
            _upsert_record(table, msg, dedupe_on, index, stats, created_ids, updated_ids)
        final_rows, prov_ok, prov_comment = [], True, "all rows trace to input messages"
        for r in table.records.all():
            final_rows.append(r.data or {})
            ids = {s.get("external_id") for s in (r.sources or []) if isinstance(s, dict)}
            if not ids or not ids <= input_ids:
                prov_ok, prov_comment = False, f"row sources {ids} not subset of {input_ids}"
        return {"rows_created": stats["rows_created"], "rows_updated": stats["rows_updated"],
                "final_rows": final_rows, "provenance_ok": prov_ok, "provenance_comment": prov_comment}
    finally:
        table.delete()


SKILL_RUNNERS = {
    "extraction": (run_extraction, scorers.score_extraction),
    "filter": (run_filter, scorers.score_filter),
    "dsl": (run_dsl, scorers.score_dsl),
    "upsert": (run_upsert, scorers.score_upsert),
}


# ---------------------------------------------------------------------------
# Tasks + evaluators (shared by the Langfuse experiment path and offline path)
# ---------------------------------------------------------------------------

def _case_from(item):
    """Reconstruct a scorer 'case' from a dataset/local item."""
    return {**(item.input or {}), "expect": item.expected_output or {}}


def system_task(*, item, **kwargs):
    data = item.input or {}
    run = run_agent(data.get("input", ""), data.get("setup"))
    # created_slugs -> list so the output is JSON-serializable for the trace
    return {"calls": run["calls"], "text": run["text"], "created_slugs": list(run["created_slugs"])}


def system_evaluator(*, input, output, expected_output=None, metadata=None, **kwargs):
    from langfuse import Evaluation

    case = {**(input or {}), "expect": expected_output or {}}
    scores = scorers.score_system_prompt(case, output)
    return [Evaluation(name=d, value=s["value"], comment=s.get("comment")) for d, s in scores.items()]


def skills_task(*, item, **kwargs):
    data = item.input or {}
    runner, _ = SKILL_RUNNERS[data["skill"]]
    return runner(data)


def skills_evaluator(*, input, output, expected_output=None, metadata=None, **kwargs):
    from langfuse import Evaluation

    case = {**(input or {}), "expect": expected_output or {}}
    _, scorer = SKILL_RUNNERS[(input or {})["skill"]]
    scores = scorer(case, output)
    return [Evaluation(name=d, value=s["value"], comment=s.get("comment")) for d, s in scores.items()]


SUITES = {
    "system": {"dataset": "sift-system-prompt", "golden": "system_prompt.jsonl",
               "task": system_task, "evaluator": system_evaluator, "title": "SUITE 1 — SYSTEM PROMPT"},
    "skills": {"dataset": "sift-skills", "golden": "skills.jsonl",
               "task": skills_task, "evaluator": skills_evaluator, "title": "SUITE 2 — SKILLS"},
}


# ---------------------------------------------------------------------------
# Runners: Langfuse experiment (linked, comparable) or offline (table + report)
# ---------------------------------------------------------------------------

class _LocalItem:
    """Mirrors a Langfuse DatasetItem for the offline path (.input/.expected_output)."""

    def __init__(self, payload, expect):
        self.input = payload
        self.expected_output = expect
        self.metadata = {}
        self.id = payload.get("id")


def _rows_from_evaluations(case_id, evaluations):
    return [{"case": case_id, "dimension": e.name, "value": e.value, "comment": e.comment or ""}
            for e in evaluations]


def run_suite_experiment(suite):
    """Run as a Langfuse dataset experiment → a linked, comparable run + URL."""
    cfg = SUITES[suite]
    dataset = tracing.get_langfuse().get_dataset(cfg["dataset"])
    result = dataset.run_experiment(
        name=f"{suite} · {PROMPT_HASH} · {GIT_SHA}",
        description=f"Sift {suite} eval — prompt {PROMPT_HASH}, git {GIT_SHA}",
        task=cfg["task"], evaluators=[cfg["evaluator"]],
        max_concurrency=1,  # serial: real-LLM calls + temp-table DB writes
    )
    rows = []
    for ir in result.item_results:
        case_id = (ir.item.input or {}).get("id") or ir.item.id
        rows.extend(_rows_from_evaluations(case_id, ir.evaluations))
    return rows, getattr(result, "dataset_run_url", None)


def run_suite_offline(suite):
    """Run locally without Langfuse: same task+evaluator, table + JSON report."""
    cfg = SUITES[suite]
    rows = []
    for case in _load_jsonl(os.path.join(GOLDEN, cfg["golden"])):
        payload = {k: v for k, v in case.items() if k != "expect"}
        item = _LocalItem(payload, case.get("expect", {}))
        output = cfg["task"](item=item)
        evals = cfg["evaluator"](input=item.input, output=output, expected_output=item.expected_output)
        rows.extend(_rows_from_evaluations(payload.get("id"), evals))
    return rows, None


def _print_suite(title, rows):
    print(f"\n=== {title} ===")
    by_dim = {}
    for r in rows:
        by_dim.setdefault(r["dimension"], []).append(r["value"])
    for case_id in dict.fromkeys(r["case"] for r in rows):
        parts = [f"{r['dimension']}={r['value']:.2f}" for r in rows if r["case"] == case_id]
        print(f"  {str(case_id):<26} " + "  ".join(parts))
    print("  " + "-" * 60)
    for dim, vals in by_dim.items():
        print(f"  {dim:<26} avg={sum(vals) / len(vals):.3f}  (n={len(vals)})")


def main():
    which = (sys.argv[1] if len(sys.argv) > 1 else "all").lower()
    suites = ["system", "skills"] if which == "all" else [which]
    use_experiment = tracing.enabled()

    report = {
        "git_sha": GIT_SHA, "prompt_hash": PROMPT_HASH,
        "client": "real" if os.environ.get("HERMES_API_KEY") else "mock",
        "langfuse": use_experiment,
        "ran_at": datetime.now(timezone.utc).isoformat(), "suites": {}, "urls": {},
    }

    for suite in suites:
        rows, url = (run_suite_experiment(suite) if use_experiment else run_suite_offline(suite))
        _print_suite(SUITES[suite]["title"], rows)
        report["suites"][suite] = rows
        if url:
            report["urls"][suite] = url
            print(f"  view run → {url}")

    all_rows = [r for s in report["suites"].values() for r in s]
    overall = (sum(r["value"] for r in all_rows) / len(all_rows)) if all_rows else 0.0
    report["overall"] = round(overall, 4)
    print(f"\nOVERALL mean score: {overall:.3f}  "
          f"(client={report['client']}, langfuse={report['langfuse']}, "
          f"prompt {PROMPT_HASH}, git {GIT_SHA})")

    os.makedirs(REPORTS, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = os.path.join(REPORTS, f"{which}-{stamp}-{GIT_SHA}.json")
    with open(path, "w") as fh:
        json.dump(report, fh, indent=2)
    print(f"report → {os.path.relpath(path, BACKEND)}")
    tracing.flush()


if __name__ == "__main__":
    main()
