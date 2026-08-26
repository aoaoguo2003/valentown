"""可观测性的**写**那一侧：把运行时发生的事追加成结构化日志。

读那一侧在 ``metrics.py``——它把这里写下的行还原成一轮一轮的决策，
汇总成能横向比较的数字。分开是因为这个模块在决策的热路径上，
每一次 LLM 调用都要过它。

每个 LLM 请求都会流经同一个总入口（``LLMClient._post_with_retries``），
并在这里被追加为一条结构化的 JSONL 记录：包含 prompt、response、耗时、
token 用量、重试次数以及最终结果。所有在 ``trace_operation`` 代码块内
发起的调用会共享同一个 ``trace_id``，这样一整个逻辑操作（一次决策、
一段对话、一次反思）就可以被完整地还原出来。

追踪功能绝不能影响模拟本身的运行：任何写入失败都会被静默吞掉。
"""

import json
import threading
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path

from config import ACTION_TRACE_FILE, LLM_TRACE_ENABLED, LLM_TRACE_FILE, LLM_TRACE_MAX_CHARS

_current_trace = ContextVar("current_trace", default=None)
_write_lock = threading.Lock()


@contextmanager
def trace_operation(operation, agent_name=None):
    """将代码块内发起的每一次 LLM 调用归入同一个 trace id。

    ``operation`` 是一个粗粒度的标签（decision / dialogue / reflection /
    action_memory），后续会用它按操作类型做汇总统计。"""
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


def log_action_event(record):
    """把一次工具调用的结果（接受/拒绝、理由、observation）追加到动作日志。

    这些事件是 ReAct 循环的行为数据：无效工具调用率、平均重规划次数、
    各类拒绝原因的分布，全部从这里统计。和 LLM 调用日志分开存，因为
    两者的字段结构和消费方式都不同。永远不会抛出异常。"""
    if not LLM_TRACE_ENABLED:
        return

    entry = {"ts": datetime.now().isoformat(timespec="milliseconds")}
    entry.update(record)

    try:
        path = Path(ACTION_TRACE_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(entry, ensure_ascii=False)
        with _write_lock:
            with path.open("a", encoding="utf-8") as file:
                file.write(line + "\n")
    except OSError:
        pass  # 可观测性绝不能拖垮模拟


def log_llm_call(record):
    """将一条 LLM 调用记录以 JSON 行的形式追加写入。永远不会抛出异常。"""
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
        pass  # 可观测性功能绝不能拖垮整个模拟
