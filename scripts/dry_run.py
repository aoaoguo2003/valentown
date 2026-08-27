#!/usr/bin/env python3
"""离线试跑：用真实 LLM 驱动整座小镇，看模型到底会怎么用这套工具。

单元测试验证的是"循环逻辑对不对"——它们全部用脚本化的假 LLM，模型永远按
剧本走。这个脚本回答的是另一个问题：**真实模型面对十四个工具会怎么做**。

要看的东西：

  * 它自发会用哪些工具？还是十几轮只会 ``move_to``？
  * 被环境拒绝之后是真的重新规划，还是换个说法再撞一次？
  * 一轮平均几步？会不会查东西查到步数用完还没做出行动？

跑的过程交给 ``runtime.scheduler.Town``——和 ``evals/runner.py`` 是同一个
引擎。这里只负责**把每一步打给人看**，以及跑完之后出一份汇总。

⚠️ 汇总不再自己数一遍，而是跑完读自己那份动作日志，交给
``observability.metrics`` 算。同一套指标，线上日志和试跑日志算出来的
含义完全一样——而且少了一份"内存里数的"和"日志里记的"对不上的可能。

用法::

    python scripts/dry_run.py                              # 两天，七个人
    python scripts/dry_run.py --days 1 --max-decisions 6   # 先测速用
    python scripts/dry_run.py --scenario errand            # 埋一个起因，验证协作链
"""

import argparse
import os
import sys
import time
from datetime import datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

# Windows 控制台默认 GBK，输出里的重音字母和符号会抛 UnicodeEncodeError，
# 而且是在工作线程里抛——一个字符就能杀掉一次决策。
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

# 追踪日志另存，免得污染正常运行的记录。必须在导入 config 之前设好。
STAMP = datetime.now().strftime("%Y%m%d-%H%M%S")
LOG_DIR = BACKEND / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
ACTION_TRACE = LOG_DIR / f"dryrun_action_{STAMP}.jsonl"
LLM_TRACE = LOG_DIR / f"dryrun_llm_{STAMP}.jsonl"
os.environ["LLM_TRACE_FILE"] = str(LLM_TRACE)
os.environ["ACTION_TRACE_FILE"] = str(ACTION_TRACE)

from evals.scenarios import SCENARIO_REGISTRY                # noqa: E402
from observability import metrics                            # noqa: E402
from runtime.scheduler import Town                           # noqa: E402
from world.clock import format_clock                         # noqa: E402
# 用模块引用：Town 会把 weather_service 换成确定性的那一个，
# 在顶层 `from ... import weather_service` 会绑死原来那个对象。
import world.weather as weather_module                       # noqa: E402
from world.weather import describe                           # noqa: E402


def print_step(event):
    """每做完一次决策，把这一轮试过什么、环境回了什么全打出来。"""
    print(f"\nday {event['life_day']}  {format_clock(event['minute']):>8}  "
          f"{event['agent'].name}   [{event['elapsed']:.1f}s]")
    for index, entry in enumerate(event["steps"], 1):
        mark = "   " if entry["ok"] else "[x] "
        print(f"   {index}. {mark}{entry['tool']}({entry['summary']})")
        thought = (entry.get("thought") or "").strip()
        if thought:
            print(f"        thought: {thought}")
        print(f"        -> {entry['observation'][:160]}")
    if event["decision"].get("source") != "llm":
        print(f"      !! fell back ({event['decision'].get('source')})")
    sys.stdout.flush()


def print_day_start(life_day):
    service = weather_module.weather_service
    codes = service.for_day(life_day)
    print(f"\n{'=' * 78}")
    print(f"DAY {life_day}   weather: {describe(codes[9])} at 9am, "
          f"{describe(codes[15])} at 3pm   "
          f"(source: {service.source_for(life_day)})")
    print(f"{'=' * 78}")


def print_day_end(life_day, report):
    print(f"\n--- end of day {life_day} ---")
    print(f"  restocked unowned shops; benefit paid: {report['benefit_paid']}")
    for name, answer in report["reflections"]:
        print(f"  {name}: {answer[:110]}")


def reports(action_trace, llm_trace):
    """行为和成本都从**自己那两份日志**里算——不在内存里另数一遍。

    ⚠️ 两边形状不同：``format_report`` 要的是 ``summarise`` 的结果，
    ``format_cost_report`` 要的是 ``summarise_cost`` 的结果。少套一层
    不会在导入时报错——它等整整一次跑结束、二十四分钟之后才炸，
    而那时候仿真数据其实都好好的，只是报告打不出来。真发生过一次，
    所以这段被抽出来，好让测试碰得到它。
    """
    return "\n\n".join((
        metrics.format_report(metrics.summarise(metrics.load(action_trace)),
                              title="behaviour"),
        metrics.format_cost_report(metrics.summarise_cost(metrics.load(llm_trace)),
                                   title="cost"),
    ))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=2)
    parser.add_argument("--max-decisions", type=int, default=None,
                        help="先测速用：跑够这么多次决策就停")
    parser.add_argument("--scenario", choices=sorted(SCENARIO_REGISTRY), default=None,
                        help="埋一个起因，逼出协作链（自然跑永远跑不出协作）")
    parser.add_argument("--live-weather", action="store_true",
                        help="用真实伦敦天气。默认关掉，让两次跑可比")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    from config import LLM_API_KEY, LLM_MODEL
    if not LLM_API_KEY:
        print("No LLM_API_KEY — set it in backend/.env first.")
        return 1
    print(f"model: {LLM_MODEL}   days: {args.days}")

    scenario = SCENARIO_REGISTRY.get(args.scenario) if args.scenario else None

    started = time.monotonic()
    with Town(days=args.days,
              max_decisions=args.max_decisions,
              deterministic_weather=not args.live_weather,
              on_decision=None if args.quiet else print_step) as town:
        if scenario:
            scenario.seed(town)
            print(f"\n[scenario: {scenario.name}]  {scenario.headline}")
            print(f"{scenario.setup}\n")

        reason = town.run(on_day_start=print_day_start,
                          on_day_end=None if args.quiet else print_day_end)

        verdict = scenario.judge(town) if scenario else None

    elapsed = time.monotonic() - started

    print(f"\n\n{'=' * 78}")
    print("SUMMARY")
    print(f"{'=' * 78}")
    print(f"  stopped because      {reason}")
    print(f"  decisions            {town.decisions}")
    print(f"  llm calls            {town.llm_calls}")
    print(f"  wall clock           {elapsed / 60:.1f} min")
    if town.latencies:
        ordered = sorted(town.latencies)
        print(f"  per-decision latency median {ordered[len(ordered) // 2]:.1f}s  "
              f"p90 {ordered[int(len(ordered) * 0.9)]:.1f}s")

    if verdict:
        mark = "PASS" if verdict["passed"] else "FAIL"
        print(f"\n  scenario {scenario.name}: {mark}")
        print(f"    {verdict['detail']}")

    print()
    print(reports(ACTION_TRACE, LLM_TRACE))

    print(f"\n  traces written to\n    {ACTION_TRACE}\n    {LLM_TRACE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
