#!/usr/bin/env python3
"""跑评估：场景 x 消融 x 重复，出一张记分卡。

    python -m evals.runner                                   # 四道题，只跑基线
    python -m evals.runner --scenario errand --ablate none,single-step
    python -m evals.runner --scenario rendezvous --ablate all --repeats 2

每一格是一座独立的小镇（``runtime.scheduler.Town``），进去之前埋起因，
跑的时候每批决策问一次判据，**一过就停**——省时间，而且"用了几次决策"
本身就是个指标。

跑的过程和 ``scripts/dry_run.py`` 是同一个引擎；这里多的只是**判据**
和**消融**。判据只看世界状态，行为指标从每格自己的动作日志里算。
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from evals.run_dir import make_run_dir, note_from_argv, write_manifest  # noqa: E402

# 每一格的 LLM 追踪都单独存，必须在导入 config 之前把目录定下来——所以
# 版本号和 --note 也得在这里就拿到，赶在 argparse 之前。
RUN_DIR = make_run_dir("eval", note_from_argv(sys.argv[1:]))
os.environ["LLM_TRACE_FILE"] = str(RUN_DIR / "llm.jsonl")

from evals.ablations import ABLATION_REGISTRY                # noqa: E402
from evals.report import (                                   # noqa: E402
    format_comparison,
    format_cost_table,
    format_scorecard,
)
from evals.scenarios import SCENARIO_REGISTRY                # noqa: E402
from llm import LLMClient                                    # noqa: E402
from observability import metrics                            # noqa: E402
from runtime.scheduler import Town                           # noqa: E402


def run_cell(scenario, ablation, attempt, verbose=True):
    """跑一格：一座小镇，一道题，一种消融。"""
    label = f"{scenario.name}/{ablation.name}#{attempt}"
    stem = f"{scenario.name}__{ablation.name}__{attempt}"
    trace = RUN_DIR / f"{stem}.jsonl"
    llm_trace = RUN_DIR / f"{stem}.llm.jsonl"
    started = time.monotonic()

    if verbose:
        print(f"\n>>> {label}   {ablation.headline}")
        sys.stdout.flush()

    town = Town(
        days=scenario.days,
        max_decisions=scenario.max_decisions,
        max_steps=ablation.max_steps,
        tools_disabled=ablation.tools_disabled,
        filter_tools=ablation.filter_tools,
        omit_context=ablation.omit_context,
        handover_windows=ablation.handover_windows,
        deterministic_weather=True,     # 天气必须钉死，否则比的是天气不是模型
        reflect=False,                  # 反思每天 7 次 LLM，对判据没有影响
        trace_file=trace,
        llm_trace_file=llm_trace,
    )

    # 走到哪一环了。**很多里程碑转瞬即逝**——Emma 借到钱那一刻余额是 8，
    # 买完药就变成 0；药在她手上，交出去就没了。所以每批决策查一次，
    # 记的是**最高水位**，只在最后查等于什么都看不见。
    reached = []

    def watch():
        for stage in scenario.stages:
            if stage.name not in reached and stage.reached(town):
                reached.append(stage.name)
        return bool(scenario.judge(town)["passed"])

    with town:
        scenario.seed(town)
        watch()                      # 开局也照一次，免得漏掉埋点自带的进度
        town.stop_when = watch
        reason = town.run()
        watch()
        verdict = scenario.judge(town)

    elapsed = time.monotonic() - started
    summary = metrics.summarise(metrics.load(trace))
    cost = metrics.summarise_cost(metrics.load(llm_trace))

    # 这一格的数据可信吗？模型一次都没成功应答过，那这一格量的是后端，
    # 不是模型——它绝不能以 FAIL 的身份进对照表。
    usable = cost.get("calls", 0) == 0 or cost["by_status"].get("success", 0) > 0

    if verbose:
        mark = ("ERR " if not usable
                else {True: "PASS", False: "FAIL", None: "----"}[verdict["passed"]])
        tokens = cost.get("tokens", {}).get("total", 0)
        walked = f"  走到 {len(reached)}/{len(scenario.stages)} 环" if scenario.stages else ""
        print(f"    {mark}  {town.decisions} 次决策 / {elapsed:.0f}s / "
              f"{tokens} tokens{walked}   {verdict['detail']}")
        sys.stdout.flush()

    return {
        "scenario": scenario.name,
        "ablation": ablation.name,
        "headline": ablation.headline,
        "attempt": attempt,
        "passed": verdict["passed"],
        "detail": verdict["detail"],
        "decisions": town.decisions,
        "llm_calls": town.llm_calls,
        "stopped_because": reason,
        "wall_seconds": elapsed,
        "trace": trace.name,
        "usable": usable,
        "stages": [stage.name for stage in scenario.stages],
        "reached": list(reached),
        "metrics": summary,
        "cost": cost,
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", default="all",
                        help="逗号分隔，或 all。可选：" + ", ".join(sorted(SCENARIO_REGISTRY)))
    parser.add_argument("--ablate", default="none",
                        help="逗号分隔，或 all。可选：" + ", ".join(sorted(ABLATION_REGISTRY)))
    parser.add_argument("--repeats", type=int, default=1,
                        help="每格跑几次。模型有温度，一次跑不出稳定结论")
    parser.add_argument("--note", default=None,
                        help="给这次跑起个名字，进目录名：eval_v8_修了递交")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    from config import LLM_API_KEY, LLM_MODEL
    if not LLM_API_KEY:
        print("No LLM_API_KEY — set it in backend/.env first.")
        return 1

    def pick(raw, registry, what):
        names = sorted(registry) if raw == "all" else [n.strip() for n in raw.split(",")]
        unknown = [n for n in names if n not in registry]
        if unknown:
            print(f"没有这个{what}：{unknown}。可选：{sorted(registry)}")
            return None
        return [registry[n] for n in names]

    scenarios = pick(args.scenario, SCENARIO_REGISTRY, "场景")
    ablations = pick(args.ablate, ABLATION_REGISTRY, "消融")
    if scenarios is None or ablations is None:
        return 2

    cells = len(scenarios) * len(ablations) * args.repeats
    budget = sum(s.max_decisions for s in scenarios) * len(ablations) * args.repeats
    print(f"model: {LLM_MODEL}")
    print(f"计划：{len(scenarios)} 道题 x {len(ablations)} 种消融 x {args.repeats} 次 "
          f"= {cells} 格")
    print(f"上限 {budget} 次决策（判据一过就早停，实际会少很多）")

    manifest = write_manifest(
        RUN_DIR, ["python", "-m", "evals.runner", *(argv or sys.argv[1:])],
        model=LLM_MODEL,
        scenarios=[s.name for s in scenarios],
        ablations=[a.name for a in ablations],
        repeats=args.repeats,
    )
    print(f"日志：{RUN_DIR}   commit {manifest['commit']}"
          f"{'（工作区有未提交改动，这个号不足以定位代码）' if manifest['dirty'] else ''}")

    # 每跑完一格立刻落盘。整张表要跑一个多小时，只在最后写的话，
    # 中途一次 Ctrl-C 或一次卡死就把已经花掉的钱全扔了。
    incremental = RUN_DIR / "rows.jsonl"

    rows, fatal = [], False
    for scenario in scenarios:
        for ablation in ablations:
            for attempt in range(1, args.repeats + 1):
                try:
                    row = run_cell(scenario, ablation, attempt, verbose=not args.quiet)
                except Exception as error:            # noqa: BLE001
                    # 一格炸了不该带走整张表。
                    print(f"    !! {scenario.name}/{ablation.name}#{attempt} "
                          f"raised: {error!r}")
                    continue
                rows.append(row)
                with incremental.open("a", encoding="utf-8") as file:
                    file.write(json.dumps(row, ensure_ascii=False) + "\n")
                print(f"    [{len(rows)}/{cells}]", flush=True)

                if LLMClient.fatal_error:
                    # 上一次没有这道闸，于是又跑了三十格废数据、烧掉一小时。
                    print(f"\n!! 中止：{LLMClient.fatal_error}")
                    print(f"   已跑完的 {len(rows)} 格结果保留在 {incremental}")
                    fatal = True
                    break
            if fatal:
                break
        if fatal:
            break

    if not rows:
        print("\n一格都没跑成。")
        return 1

    print()
    print(format_scorecard(rows))
    print(format_cost_table(rows))
    print(format_comparison(rows))

    out = RUN_DIR / "scorecard.json"
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n每格的完整结果写到 {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
