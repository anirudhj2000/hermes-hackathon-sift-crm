"""Scorers for Sift's two eval suites.

Every scorer returns a dict {dimension: {"value": float 0..1, "comment": str}}.
Rule scorers are deterministic and need no model. `narration_quality` uses an
LLM judge when HERMES_API_KEY is set, and degrades to a cheap heuristic offline.

Suite 1 (system prompt) scores the agent's *decisions*, read off the recorded
tool calls + narration of a dry (side-effect-free) run.
Suite 2 (skills) scores the pipeline's tool-level units directly.
"""

import os
import re


def _norm(v):
    return re.sub(r"\s+", " ", str(v).strip().lower()) if v is not None else None


def _text_match(expected, actual):
    """Lenient text equality: exact (normalized) or one contains the other."""
    e, a = _norm(expected), _norm(actual)
    if e is None and a is None:
        return True
    if e is None or a is None:
        return False
    return e == a or e in a or a in e


# ---------------------------------------------------------------------------
# Suite 1 — system prompt (agent planning & behavior)
# ---------------------------------------------------------------------------

def _calls_of(run, name):
    return [c for c in run["calls"] if c["name"] == name]


def _last_workflow_dsl(run):
    wfs = _calls_of(run, "create_workflow")
    return (wfs[-1]["args"].get("dsl") or {}) if wfs else {}


def _fetch_sources(dsl):
    return sorted(
        {s.get("source") for s in dsl.get("steps", []) if s.get("type") == "fetch" and s.get("source")}
    )


def _score_schema_design(case, run):
    want = (case["expect"].get("table") or {}).get("has_columns") or []
    tables = _calls_of(run, "create_table")
    if not tables:
        return {"value": 0.0, "comment": "no create_table call"}
    cols = tables[-1]["args"].get("columns") or []
    names = {(_norm(c.get("name"))) for c in cols if isinstance(c, dict)}
    valid_types = all(
        c.get("type") in ("text", "number", "date", "bool", "enum") for c in cols if isinstance(c, dict)
    )
    hit = sum(1 for w in want if _norm(w) in names)
    frac = (hit / len(want)) if want else 1.0
    value = frac if valid_types else frac * 0.5
    return {"value": round(value, 3), "comment": f"{hit}/{len(want)} expected columns, types_valid={valid_types}"}


def _score_dedupe_choice(case, run):
    tables = _calls_of(run, "create_table")
    if not tables:
        return {"value": 0.0, "comment": "no create_table call"}
    args = tables[-1]["args"]
    keys = args.get("dedupe_keys") or []
    col_names = {_norm(c.get("name")) for c in (args.get("columns") or []) if isinstance(c, dict)}
    need_nonempty = (case["expect"].get("table") or {}).get("dedupe_keys_nonempty")
    subset = all(_norm(k) in col_names for k in keys)
    ok = subset and (bool(keys) if need_nonempty else True)
    return {"value": 1.0 if ok else 0.0, "comment": f"dedupe_keys={keys} subset={subset}"}


def _score_trigger_selection(case, run):
    dsl = _last_workflow_dsl(run)
    want = case["expect"].get("workflow") or {}
    trig = dsl.get("trigger")
    if want.get("trigger_type") == "manual":
        ok = trig == "manual"
        return {"value": 1.0 if ok else 0.0, "comment": f"trigger={trig!r}"}
    ok = isinstance(trig, dict) and trig.get("type") == "interval" and trig.get("minutes") == want.get("trigger_minutes")
    return {"value": 1.0 if ok else 0.0, "comment": f"trigger={trig!r} want interval {want.get('trigger_minutes')}m"}


def _score_source_selection(case, run):
    dsl = _last_workflow_dsl(run)
    got = _fetch_sources(dsl)
    want = sorted(case["expect"].get("workflow", {}).get("sources") or [])
    ok = got == want
    return {"value": 1.0 if ok else 0.0, "comment": f"sources={got} want {want}"}


def _score_tool_sequence(case, run):
    order = [c["name"] for c in run["calls"]]
    want = case["expect"].get("tools_called") or []
    # subsequence check: want appears in order, in order
    it = iter(order)
    in_order = all(any(o == w for o in it) for w in want)
    # create_workflow must target a slug create_table actually returned
    grounded_slug = True
    ct = _calls_of(run, "create_table")
    cw = _calls_of(run, "create_workflow")
    if ct and cw:
        returned = {c["result"].get("slug") for c in ct if isinstance(c.get("result"), dict)}
        grounded_slug = (cw[-1]["args"].get("dsl") or {}).get("table") in returned
    ok = in_order and grounded_slug
    return {"value": 1.0 if ok else 0.0, "comment": f"order={order} grounded_slug={grounded_slug}"}


def _score_qa_routing(case, run):
    names = [c["name"] for c in run["calls"]]
    ok = "list_tables" in names and "create_table" not in names
    return {"value": 1.0 if ok else 0.0, "comment": f"calls={names}"}


def _score_grounding(case, run):
    problems = []
    registry = {"whatsapp", "gmail"}
    for c in run["calls"]:
        res = c.get("result") or {}
        if isinstance(res, dict) and res.get("error") == "unknown tool":
            problems.append(f"unknown tool {c['name']}")
    for cw in _calls_of(run, "create_workflow"):
        dsl = cw["args"].get("dsl") or {}
        for s in _fetch_sources(dsl):
            if s not in registry:
                problems.append(f"invented source {s!r}")
        tbl = dsl.get("table")
        created = run["created_slugs"]
        if tbl and tbl not in created and not _calls_of(run, "create_table") == []:
            # workflow targets a slug that was never created this run
            if tbl not in created:
                problems.append(f"ungrounded table slug {tbl!r}")
    ok = not problems
    return {"value": 1.0 if ok else 0.0, "comment": "; ".join(problems) or "grounded"}


def _score_scope_discipline(case, run):
    # Expected when whatsapp is requested but no chats are scoped: the agent
    # should ask the user to scope, not fabricate a whatsapp workflow.
    made_wa_wf = any(
        "whatsapp" in _fetch_sources(cw["args"].get("dsl") or {})
        for cw in _calls_of(run, "create_workflow")
    )
    mentions_scope = bool(re.search(r"scope|sync|whatsapp page|scoped", run["text"], re.I))
    ok = (not made_wa_wf) and mentions_scope
    return {
        "value": 1.0 if ok else 0.0,
        "comment": f"made_whatsapp_workflow={made_wa_wf} asked_to_scope={mentions_scope}",
    }


def _score_narration_quality(case, run):
    text = run["text"].strip()
    score = llm_judge_narration(case["input"], text)
    if score is not None:
        return {"value": round(score, 3), "comment": "llm-judge"}
    # Offline heuristic: rewards a non-trivial, on-topic narration.
    hints = 0
    if len(text) > 60:
        hints += 1
    if _calls_of(run, "create_table") and re.search(r"table|schema|column", text, re.I):
        hints += 1
    if re.search(r"pipeline|workflow|run|fill|sift", text, re.I):
        hints += 1
    return {"value": round(hints / 3, 3), "comment": "heuristic (no judge model)"}


SYSTEM_SCORERS = {
    "schema_design": _score_schema_design,
    "dedupe_choice": _score_dedupe_choice,
    "trigger_selection": _score_trigger_selection,
    "source_selection": _score_source_selection,
    "tool_sequence": _score_tool_sequence,
    "qa_routing": _score_qa_routing,
    "grounding": _score_grounding,
    "scope_discipline": _score_scope_discipline,
    "narration_quality": _score_narration_quality,
}


def score_system_prompt(case, run):
    dims = case["expect"].get("dimensions") or list(SYSTEM_SCORERS)
    return {d: SYSTEM_SCORERS[d](case, run) for d in dims if d in SYSTEM_SCORERS}


# ---------------------------------------------------------------------------
# Suite 2 — skills (tool-level competence)
# ---------------------------------------------------------------------------

def score_extraction(case, extracted):
    expected = case["expect"]
    total = len(expected) or 1
    correct = 0
    misses = []
    for key, want in expected.items():
        got = extracted.get(key)
        col_ok = _text_match(want, got) if isinstance(want, str) else (_norm(want) == _norm(got))
        if col_ok:
            correct += 1
        else:
            misses.append(f"{key}: want {want!r} got {got!r}")
    return {
        "extraction_accuracy": {
            "value": round(correct / total, 3),
            "comment": f"{correct}/{total} fields" + (f"; {', '.join(misses)}" if misses else ""),
        }
    }


def score_filter(case, flags):
    expected = case["expect"]
    n = len(expected) or 1
    correct = sum(1 for a, b in zip(flags, expected) if bool(a) == bool(b))
    return {
        "filter_relevance": {
            "value": round(correct / n, 3),
            "comment": f"{correct}/{n} correct; predicted={list(map(bool, flags))} expected={expected}",
        }
    }


def score_dsl(case, errors):
    exp = case["expect"]
    if exp.get("valid"):
        ok = not errors
        return {"dsl_validity": {"value": 1.0 if ok else 0.0, "comment": "valid" if ok else f"errors: {errors}"}}
    need = exp.get("must_contain")
    hit = bool(errors) and (need is None or any(need.lower() in e.lower() for e in errors))
    return {
        "dsl_validity": {
            "value": 1.0 if hit else 0.0,
            "comment": f"expected invalid (contains {need!r}); errors={errors}",
        }
    }


def score_upsert(case, outcome):
    """outcome = {rows_created, rows_updated, final_rows: [data...], provenance_ok: bool}"""
    exp = case["expect"]
    checks = []
    if "rows_created" in exp:
        checks.append(("rows_created", outcome["rows_created"] == exp["rows_created"]))
    if "rows_updated" in exp:
        checks.append(("rows_updated", outcome["rows_updated"] == exp["rows_updated"]))
    if "final_row_count" in exp:
        checks.append(("final_row_count", len(outcome["final_rows"]) == exp["final_row_count"]))
    for spec in exp.get("final_contains", []):
        match = any(all(_text_match(v, row.get(k)) for k, v in spec.items()) for row in outcome["final_rows"])
        checks.append((f"row~{spec}", match))
    passed = sum(1 for _, ok in checks if ok)
    total = len(checks) or 1
    fails = [name for name, ok in checks if not ok]
    result = {
        "upsert_correctness": {
            "value": round(passed / total, 3),
            "comment": f"{passed}/{total} checks" + (f"; failed: {fails}" if fails else ""),
        }
    }
    result["provenance_integrity"] = {
        "value": 1.0 if outcome.get("provenance_ok") else 0.0,
        "comment": outcome.get("provenance_comment", ""),
    }
    return result


# ---------------------------------------------------------------------------
# LLM judge (narration) — real client only; None when offline
# ---------------------------------------------------------------------------

def llm_judge_narration(user_input, narration):
    if not os.environ.get("HERMES_API_KEY") or not narration:
        return None
    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=os.environ["HERMES_API_KEY"],
            base_url=os.environ.get("HERMES_BASE_URL", "https://inference.nousresearch.com/v1"),
        )
        prompt = (
            "You are grading an AI data assistant's narration. The user asked:\n"
            f"{user_input!r}\n\nThe assistant replied:\n{narration!r}\n\n"
            "Score 0.0-1.0 how clearly and accurately it explains what it is doing "
            "(the table/schema it designs, the pipeline, the schedule) without hallucinating. "
            "Respond with ONLY the number."
        )
        resp = client.chat.completions.create(
            model=os.environ.get("HERMES_MODEL", "Hermes-4-405B"),
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        m = re.search(r"[01](?:\.\d+)?", resp.choices[0].message.content or "")
        return max(0.0, min(1.0, float(m.group(0)))) if m else None
    except Exception:
        return None
