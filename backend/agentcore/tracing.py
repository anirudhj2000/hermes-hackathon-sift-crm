"""Langfuse tracing wrapper for Sift.

Design goal: tracing must NEVER change runtime behavior. When
LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY are unset (the offline mock demo),
every helper here is a no-op and the agent runs exactly as before. Drop the
three LANGFUSE_* keys into .env and each `POST /api/agent/chat` becomes a
Langfuse trace (session_id = chat_id) with a generation per model turn and a
span per tool call, carrying token usage and cost.

Langfuse Python SDK v4 surface used:
  get_client(), client.start_as_current_observation(as_type=..., name=..., model=...),
  obs.update(input=/output=/usage_details=/cost_details=), obs.update_trace(session_id=/input=/output=),
  client.score_current_trace(name=/value=/data_type=), client.flush().
"""

import os
from contextlib import contextmanager

# Per-1K-token USD pricing by model-name substring. Only used to fill
# cost_details when the provider doesn't return cost itself. Adjust to the real
# rate card; unknown models trace with no cost rather than a wrong one.
PRICING = {
    "gpt-5": (0.00125, 0.010),
    "gpt-4o": (0.0025, 0.010),
    "gpt-4": (0.03, 0.06),
    "hermes": (0.0, 0.0),  # self-hosted / unknown → 0
}

_client = None
_resolved = False


def enabled():
    return bool(
        os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY")
    )


def get_langfuse():
    """Return the singleton Langfuse client, or None when disabled/unavailable."""
    global _client, _resolved
    if _resolved:
        return _client
    _resolved = True
    if not enabled():
        return None
    try:
        from langfuse import get_client

        _client = get_client()
    except Exception:
        _client = None
    return _client


def price(model, input_tokens, output_tokens):
    """cost_details dict for a generation, or None if the model isn't priced."""
    key = next((k for k in PRICING if k in (model or "").lower()), None)
    if key is None:
        return None
    p_in, p_out = PRICING[key]
    return {
        "input": round((input_tokens or 0) / 1000 * p_in, 6),
        "output": round((output_tokens or 0) / 1000 * p_out, 6),
    }


class _NoopSpan:
    """Stands in for a Langfuse observation when tracing is disabled."""

    def update(self, **kw):
        return self

    def set_trace_io(self, **kw):
        return self

    def score_trace(self, **kw):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@contextmanager
def trace(name, session_id=None, input=None, metadata=None):
    """Root of a trace. Sets trace-level attributes (session_id, name, metadata)
    via propagate_attributes so every child observation inherits them, and
    yields the root span. Caller sets the final trace output with
    `root.set_trace_io(output=...)`. No-ops when Langfuse is disabled.
    """
    lf = get_langfuse()
    if lf is None:
        yield _NoopSpan()
        return
    try:
        from langfuse import propagate_attributes

        pa = {}
        if session_id:
            pa["session_id"] = session_id
        if name:
            pa["trace_name"] = name
        if metadata:
            pa["metadata"] = metadata
        with propagate_attributes(**pa):
            # Trace-level I/O is inferred from the root observation, so setting
            # the root span's input/output (below, and via the caller's
            # root.update(output=...)) populates the trace without the
            # deprecated set_trace_io path.
            with lf.start_as_current_observation(as_type="span", name=name, input=input) as root:
                yield root
    except Exception:
        yield _NoopSpan()


@contextmanager
def observation(as_type, name, model=None, input=None):
    """Start a child span or generation as the current observation. Yields a
    handle exposing .update(...); no-ops when Langfuse is disabled."""
    lf = get_langfuse()
    if lf is None:
        yield _NoopSpan()
        return
    kwargs = {"as_type": as_type, "name": name}
    if model is not None:
        kwargs["model"] = model
    if input is not None:
        kwargs["input"] = input
    try:
        cm = lf.start_as_current_observation(**kwargs)
    except Exception:
        yield _NoopSpan()
        return
    with cm as obs:
        yield obs


def score_current_trace(name, value, data_type="NUMERIC", comment=None):
    """Attach a score to the current trace (used by the eval harness)."""
    lf = get_langfuse()
    if lf is None:
        return
    try:
        lf.score_current_trace(name=name, value=value, data_type=data_type, comment=comment)
    except Exception:
        pass


def flush():
    lf = get_langfuse()
    if lf is not None:
        try:
            lf.flush()
        except Exception:
            pass
