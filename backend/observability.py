"""Lightweight observability for LLM calls.

Every LLM request flows through one chokepoint (``LLMClient._post_with_retries``)
and is appended here as a structured JSONL trace: prompt, response, latency,
token usage, retries, and outcome. Calls made inside a ``trace_operation`` block
share one ``trace_id`` so a whole logical operation (a decision, a dialogue, a
reflection) can be reconstructed end to end.

Tracing must never break the simulation: any failure to write is swallowed.
"""

import json
import threading
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path

from config import LLM_TRACE_ENABLED, LLM_TRACE_FILE, LLM_TRACE_MAX_CHARS

_current_trace = ContextVar("current_trace", default=None)
_write_lock = threading.Lock()


@contextmanager
def trace_operation(operation, agent_name=None):
    """Group every LLM call made inside the block under one trace id.

    ``operation`` is a coarse label (decision / dialogue / reflection /
    action_memory) used later for per-operation aggregation."""
    token = _current_trace.set({
        "trace_id": uuid.uuid4().hex[:12],
        "operation": operation,
        "agent_name": agent_name,
    })
    try:
        yield
    finally:
        _current_trace.reset(token)


def current_context():
    return _current_trace.get() or {}


def _truncate(value):
    if value is None:
        return None
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    if LLM_TRACE_MAX_CHARS and len(text) > LLM_TRACE_MAX_CHARS:
        return text[:LLM_TRACE_MAX_CHARS] + f"...<+{len(text) - LLM_TRACE_MAX_CHARS} chars>"
    return text


def log_llm_call(record):
    """Append one LLM call record as a JSON line. Never raises."""
    if not LLM_TRACE_ENABLED:
        return

    ctx = current_context()
    entry = {
        "ts": datetime.now().isoformat(timespec="milliseconds"),
        "trace_id": ctx.get("trace_id"),
        "operation": ctx.get("operation"),
    }
    entry.update(record)
    entry["agent_name"] = record.get("agent_name") or ctx.get("agent_name")
    entry["prompt"] = _truncate(entry.get("prompt"))
    entry["response"] = _truncate(entry.get("response"))

    try:
        path = Path(LLM_TRACE_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(entry, ensure_ascii=False)
        with _write_lock:
            with path.open("a", encoding="utf-8") as file:
                file.write(line + "\n")
    except OSError:
        pass  # observability must never take down the simulation
