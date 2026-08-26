#!/usr/bin/env python3
"""汇总由 backend/observability/trace.py 生成的 LLM 调用追踪日志。

读取 JSONL 格式的追踪记录（每条记录对应一次 LLM 调用），并打印汇总指标：
调用量、成功/失败/降级（fallback）比率、延迟百分位数、token 用量，
以及按操作类型 / 按 agent 划分的明细。这是可观测性体系的配套工具，
将原始追踪数据转化为可用于调试模拟行为的“多维归因”信息。

用法：
    python scripts/llm_stats.py [path/to/llm_trace.jsonl]

默认使用相对于仓库根目录的 backend/logs/llm_trace.jsonl。
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

DEFAULT_TRACE = Path(__file__).resolve().parent.parent / "backend" / "logs" / "llm_trace.jsonl"


def load_records(path):
    records = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def percentile(values, pct):
    if not values:
        return 0
    ordered = sorted(values)
    rank = max(0, min(len(ordered) - 1, round((pct / 100) * (len(ordered) - 1))))
    return ordered[rank]


def summarise_group(records):
    statuses = defaultdict(int)
    latencies = []
    total_tokens = 0
    prompt_tokens = 0
    completion_tokens = 0
    retries = 0
    for record in records:
        statuses[record.get("status", "unknown")] += 1
        if record.get("status") == "success" and isinstance(record.get("latency_ms"), int):
            latencies.append(record["latency_ms"])
        total_tokens += record.get("total_tokens") or 0
        prompt_tokens += record.get("prompt_tokens") or 0
        completion_tokens += record.get("completion_tokens") or 0
        retries += max(0, (record.get("attempts") or 1) - 1)
    return {
        "calls": len(records),
        "statuses": dict(statuses),
        "latency_p50": percentile(latencies, 50),
        "latency_p95": percentile(latencies, 95),
        "total_tokens": total_tokens,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "extra_retries": retries,
    }


def print_block(title, stats):
    calls = stats["calls"]
    success = stats["statuses"].get("success", 0)
    success_rate = (success / calls * 100) if calls else 0
    print(f"\n{title}")
    print(f"  calls            : {calls}")
    print(f"  success rate     : {success_rate:.1f}%  ({stats['statuses']})")
    print(f"  latency p50 / p95: {stats['latency_p50']} ms / {stats['latency_p95']} ms")
    print(f"  tokens total     : {stats['total_tokens']}  (prompt {stats['prompt_tokens']}, completion {stats['completion_tokens']})")
    print(f"  extra retries    : {stats['extra_retries']}")


def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_TRACE
    if not path.exists():
        print(f"No trace file at {path}. Run the simulation first (or set LLM_TRACE_FILE).")
        return 1

    records = load_records(path)
    if not records:
        print(f"Trace file {path} is empty.")
        return 0

    print(f"Trace: {path}")
    print(f"Records: {len(records)}")
    print_block("OVERALL", summarise_group(records))

    by_operation = defaultdict(list)
    for record in records:
        by_operation[record.get("operation") or "(none)"].append(record)
    print("\n=== By operation ===")
    for operation in sorted(by_operation):
        print_block(operation, summarise_group(by_operation[operation]))

    by_agent = defaultdict(list)
    for record in records:
        by_agent[record.get("agent_name") or "(none)"].append(record)
    print("\n=== By agent ===")
    for agent in sorted(by_agent):
        stats = summarise_group(by_agent[agent])
        print(f"  {agent:<16} calls={stats['calls']:<4} tokens={stats['total_tokens']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
