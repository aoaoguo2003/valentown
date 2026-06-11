#!/usr/bin/env python3
"""Offline regression harness for the agent decision loop.

Runs a fixed set of scenarios through ``Agent.decide_next_action`` against the
live LLM and scores each decision on transparent, deterministic rubrics:

  * format-valid : the LLM returned a structurally valid decision that passed
                   validation (source == "llm"); otherwise the deterministic
                   fallback had to take over.
  * need-met     : the chosen destination actually addresses the scenario's
                   dominant need (see RUBRIC below).

It also pulls latency and token usage from the observability trace so effect
and cost can be tracked together across prompt/model changes.

Usage:
    python backend/eval/run_eval.py [--repeats N] [--cases path/to/cases.json]
"""

import argparse
import json
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Route this run's LLM traces to a dedicated file BEFORE importing modules that
# read the config at import time, so eval traces stay separate from sim traces.
EVAL_TRACE = BACKEND_DIR / "logs" / "eval_trace.jsonl"
os.environ["LLM_TRACE_FILE"] = str(EVAL_TRACE)

from agents.agent import (  # noqa: E402  (import after env is set)
    ALLOWED_DESTINATIONS,
    MAX_ACTION_MINUTES,
    MIN_ACTION_MINUTES,
)
import agents.agent as agent_module  # noqa: E402
from memory.memory_system import MemorySystem  # noqa: E402

# --- Scoring rubric (deterministic, transparent so it can be critiqued) ------
FOOD_ROOMS = {"Kitchen", "Dining_table", "Dinning_room"}
FOOD_AREAS = {"Supermarket", "Café_bar"}
REST_ROOMS = {"Sofa", "Reading_chair", "Chair", "Living_room", "Porch", "Window", "Bookshelf"}
PUBLIC_AREAS = {"Park", "Café_bar", "Supermarket", "Pharmacy"}

RUBRIC = {
    "hunger": "destination room in {Kitchen, Dining_table, Dinning_room} OR area in {Supermarket, Café_bar}",
    "energy": "destination is a home area with a restful anchor {Sofa, Reading_chair, Chair, Living_room, Porch, Window, Bookshelf}",
    "social": "destination area is public {Park, Café_bar, Supermarket, Pharmacy} OR talk_to != 'nobody'",
    "none": "any structurally valid action counts (no urgent need to satisfy)",
}

# Aggregation rule: when several needs are triggered at once, addressing ANY one
# of them counts as a satisfied decision. A real person can sensibly eat before
# sleeping (or vice versa); order between equally-pressing needs is not scored.
AGGREGATION_NOTE = "met = decision satisfies AT LEAST ONE actively-triggered need (any order); empty triggers => any valid action"


def _area(dest):
    return dest.split(".")[0]


def _room(dest):
    return dest.split(".")[-1]


def need_satisfied(need, decision):
    dest = decision.get("destination", "")
    area, room = _area(dest), _room(dest)
    if need == "hunger":
        return room in FOOD_ROOMS or area in FOOD_AREAS
    if need == "energy":
        return area.endswith("_home") and room in REST_ROOMS
    if need == "social":
        return area in PUBLIC_AREAS or decision.get("talk_to", "nobody") != "nobody"
    return True  # "none": any valid action is acceptable


def decision_meets_case(triggered_needs, decision):
    """A decision is satisfactory if it addresses ANY actively-triggered need;
    with no triggered needs, any structurally valid action is fine."""
    if not triggered_needs:
        return True
    return any(need_satisfied(need, decision) for need in triggered_needs)


def is_format_valid(decision):
    dest = decision.get("destination")
    action = str(decision.get("action") or "").strip()
    duration = decision.get("duration_minutes")
    return (
        dest in ALLOWED_DESTINATIONS
        and bool(action)
        and isinstance(duration, int)
        and MIN_ACTION_MINUTES <= duration <= MAX_ACTION_MINUTES
    )


def build_agents():
    memory = MemorySystem(retention_days=15)
    agents = {}
    for cls_name in dir(agent_module):
        obj = getattr(agent_module, cls_name)
        if isinstance(obj, type) and issubclass(obj, agent_module.Agent) and obj is not agent_module.Agent:
            try:
                instance = obj(memory, f"{cls_name}_home.Living_room")
            except TypeError:
                continue
            agents[instance.name] = instance
    memory.initialize_agents(list(agents.keys()))
    return agents


def load_decision_traces():
    if not EVAL_TRACE.exists():
        return []
    traces = []
    with EVAL_TRACE.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("operation") == "decision":
                traces.append(rec)
    return traces


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=1, help="runs per case")
    parser.add_argument("--cases", default=str(Path(__file__).with_name("cases.json")))
    args = parser.parse_args()

    # Keep non-ASCII anchors (e.g. "Café_bar") readable on Windows consoles.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    EVAL_TRACE.parent.mkdir(parents=True, exist_ok=True)
    EVAL_TRACE.write_text("", encoding="utf-8")  # fresh trace for this run

    with open(args.cases, encoding="utf-8") as file:
        cases = json.load(file)

    agents = build_agents()

    print("=== RUBRIC (how 'need-met' is scored) ===")
    for need, rule in RUBRIC.items():
        print(f"  {need:<7}: {rule}")
    print(f"  rule   : {AGGREGATION_NOTE}")
    print()

    results = []
    print(f"{'case':<20}{'agent':<14}{'needs':<16}{'src':<9}{'dest':<26}{'fmt':<5}{'met':<5}")
    print("-" * 96)
    for case in cases:
        agent = agents.get(case["agent"])
        if agent is None:
            print(f"{case['name']:<20}  (unknown agent {case['agent']})")
            continue
        triggered_needs = [trigger["need"] for trigger in case.get("triggers", [])]
        needs_label = ",".join(triggered_needs) if triggered_needs else "none"
        for _ in range(args.repeats):
            decision = agent.decide_next_action(
                internal_state=case["internal_state"],
                triggers=case["triggers"],
                day_number=1,
                time_text=case["time_text"],
                current_location=case["current_location"],
            )
            fmt_ok = is_format_valid(decision)
            met = decision_meets_case(triggered_needs, decision)
            results.append({
                "case": case["name"],
                "agent": case["agent"],
                "triggered_needs": triggered_needs,
                "source": decision.get("source"),
                "destination": decision.get("destination"),
                "talk_to": decision.get("talk_to"),
                "format_valid": fmt_ok,
                "need_met": met,
            })
            print(
                f"{case['name']:<20}{case['agent']:<14}{needs_label:<16}"
                f"{str(decision.get('source')):<9}{str(decision.get('destination')):<26}"
                f"{'OK' if fmt_ok else 'BAD':<5}{'OK' if met else 'MISS':<5}"
            )

    # Attach latency/tokens from the trace (decision calls are sequential).
    traces = load_decision_traces()
    for result, trace in zip(results, traces):
        result["latency_ms"] = trace.get("latency_ms")
        result["total_tokens"] = trace.get("total_tokens")
        result["llm_status"] = trace.get("status")

    total = len(results)
    llm_used = sum(1 for r in results if r["source"] == "llm")
    fmt_ok = sum(1 for r in results if r["format_valid"])
    met = sum(1 for r in results if r["need_met"])
    latencies = [r["latency_ms"] for r in results if isinstance(r.get("latency_ms"), int)]
    tokens = [r["total_tokens"] for r in results if isinstance(r.get("total_tokens"), int)]

    def pct(n):
        return f"{(n / total * 100):.1f}%" if total else "n/a"

    print("\n=== SUMMARY ===")
    print(f"  total runs          : {total}")
    print(f"  format-valid rate   : {pct(fmt_ok)}  ({fmt_ok}/{total})")
    print(f"  LLM-used rate       : {pct(llm_used)}  (rest fell back to rules)")
    print(f"  fallback rate       : {pct(total - llm_used)}")
    print(f"  need-satisfied rate : {pct(met)}  ({met}/{total})")
    if latencies:
        print(f"  avg decision latency: {sum(latencies) // len(latencies)} ms")
    if tokens:
        print(f"  total / avg tokens  : {sum(tokens)} / {sum(tokens) // len(tokens)}")

    out_path = EVAL_TRACE.with_name("eval_results.json")
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nPer-run results written to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
