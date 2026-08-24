#!/usr/bin/env python3
"""离线试跑：用真实 LLM 驱动整座小镇，看模型到底会怎么用这套工具。

单元测试验证的是"循环逻辑对不对"——它们全部用脚本化的假 LLM，模型永远
按剧本走。这个脚本回答的是另一个问题：**真实模型面对十一个工具会怎么做**。

要看的东西：

  * 它自发会用哪些工具？还是十几轮只会 ``move_to``？
  * **会不会想到用 ``stay`` 来等**？这是通信链条的关键一环。
  * 被环境拒绝之后是真的重新规划，还是换个说法再撞一次？
  * 一轮平均几步？会不会查东西查到步数用完还没做出行动？
  * prompt 有多大、每轮多少 token、多少钱。

## 调度：全局时钟，同一时刻并发

每个居民有自己的"下次决策时刻"，每轮挑**最早的那一批**来跑；同一时刻
到点的人**真的开线程并发决策**。这正是前端 game.js 的做法，也是抢座位、
邮件往返、天气变化能够自然发生的前提——各跑各的时间线，多智能体互动就
全测不出来了。

## 不碰任何真实数据

记忆、收件箱、经济、需求状态全部指向临时目录，追踪日志也另存一份。
跑完只留 ``backend/logs/dryrun_*.jsonl``，你的存档一个字节都不会变。

用法：
    python scripts/dry_run.py                  # 两天，七个人
    python scripts/dry_run.py --days 1
    python scripts/dry_run.py --max-decisions 6  # 先测速用
"""

import argparse
import os
import shutil
import sys
import tempfile
import threading
import time
from collections import Counter, defaultdict
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
os.environ["LLM_TRACE_FILE"] = str(LOG_DIR / f"dryrun_llm_{STAMP}.jsonl")
os.environ["ACTION_TRACE_FILE"] = str(LOG_DIR / f"dryrun_action_{STAMP}.jsonl")

import agent_state                                          # noqa: E402
import economy as economy_module                            # noqa: E402
import goals as goals_module                                # noqa: E402
import mailbox as mailbox_module                            # noqa: E402
from agent_state import (                                   # noqa: E402
    complete_agent_action,
    evaluate_agent_triggers,
    load_agent_state,
)
from agents.agent import (                                  # noqa: E402
    AdamHarris,
    ArthurMorgan,
    EllaParker,
    EmmaHarris,
    GavinHarris,
    MiaThompson,
    RonParker,
)
from memory.memory_system import MemorySystem               # noqa: E402
from memory.reflection import Reflection                    # noqa: E402
from runtime import run_decision_loop                       # noqa: E402
from weather import describe, weather_service               # noqa: E402
from world import World, format_clock                       # noqa: E402

WAKE_MINUTE = 6 * 60 + 30
DAY_END = 24 * 60          # 一天的终点；睡过这条线的人今天就不再决策了
WAKE_STAGGER = 10          # 起床时间错开，和前端一致

AGENT_CLASSES = [
    (RonParker, "Ron_home.Living_room"),
    (EllaParker, "Ella_home.Living_room"),
    (EmmaHarris, "Emma_home.Living_room"),
    (GavinHarris, "Gavin_home.Living_room"),
    (AdamHarris, "Adam_home.Living_room"),
    (MiaThompson, "Mia_home.Living_room"),
    (ArthurMorgan, "Arthur_home.Living_room"),
]


class DryRun:
    def __init__(self, days=2, max_decisions=None, verbose=True, scenario=None):
        self.days = days
        self.scenario = scenario
        self.max_decisions = max_decisions
        self.verbose = verbose
        self.sandbox = Path(tempfile.mkdtemp(prefix="valentown-dryrun-"))
        self.lock = threading.Lock()
        self.print_lock = threading.Lock()

        # 统计
        self.tool_calls = Counter()
        self.rejections = Counter()
        self.steps_per_turn = []
        self.sources = Counter()
        self.decisions = 0
        self.llm_calls = 0
        self.latencies = []
        self.by_agent = defaultdict(Counter)

        self._isolate()
        self._build_agents()
        self._seed()

    # --- 隔离：一个字节都不碰真实存档 -------------------------------

    def _isolate(self):
        agent_state.STATE_DIR = self.sandbox / "agent_states"
        goals_module.goal_store = goals_module.GoalStore(path=self.sandbox / "goals.json")
        economy_module.economy = economy_module.Economy(path=self.sandbox / "economy.json")
        mailbox_module.mailbox = mailbox_module.Mailbox(path=self.sandbox / "mailboxes.json")

    def _build_agents(self):
        self.memory = MemorySystem(retention_days=15, memory_dir=self.sandbox / "memories")
        self.agents = [cls(self.memory, home) for cls, home in AGENT_CLASSES]
        self.names = [agent.name for agent in self.agents]
        self.memory.initialize_agents(self.names)
        agent_state.ensure_agent_state_files(self.names)


    # --- 埋钩子 -----------------------------------------------------

    def _seed(self):
        """给世界一个起因。

        ``errand`` 这一个场景就能把整条协作链串起来，而且每一环都是**真实
        缺口**，不是硬塞的提示：

          Gavin 写信请 Emma 去买退烧药   -> 她得先读信才知道
          Emma 兜里只有 3 块，药要 8 块   -> 不开口借钱就买不成
          Adam 在家等着                  -> 药买到手还得当面交过去

        每一步都可能失败，而失败的理由都会回灌。这正是自然跑永远造不出来
        的局面——那三天里七个人各过各的，谁也不需要谁。
        """
        if self.scenario != "errand":
            return

        economy = economy_module.economy
        mailbox = mailbox_module.mailbox

        mailbox.send(
            sender="Gavin Harris",
            recipient="Emma Harris",
            subject="Adam is running a fever",
            body=("Adam has a fever and we are out of cold medicine. Could you get "
                  "some from the pharmacy today and bring it to him? I am stuck at "
                  "work until this evening."),
            life_day=1,
            time_text="6:30 AM",
        )
        # 钱刚好不够：药 8 块，她只有 3 块。差 5 块——不开口就买不成。
        economy._balances["Emma Harris"] = 3
        economy._save()

        print("\n[scenario: errand]")
        print("  Gavin -> Emma: Adam 发烧了，能去药房买退烧药带给他吗")
        print("  Emma 余额 3，退烧药 8 —— 差 5 块")
        print("  完整链条需要：读信 -> 记下任务 -> 发现钱不够 -> 借钱 -> 买 -> 当面交给 Adam\n")

    def _scenario_report(self):
        """场景成败的客观判定——看世界状态，不看模型怎么说。"""
        if self.scenario != "errand":
            return
        economy = economy_module.economy
        adam = economy.holdings("Adam Harris").get("cold_medicine", 0)
        emma = economy.holdings("Emma Harris").get("cold_medicine", 0)
        print("\n  scenario: errand")
        print(f"    Adam 手上的退烧药   {adam}    <- 任务达成与否只看这个")
        print(f"    Emma 手上的退烧药   {emma}")
        print(f"    Emma 余额          {economy.balance('Emma Harris')}")
        from goals import goal_store
        print(f"    任务状态           {dict(goal_store.stats())}")

    # --- 世界快照 ---------------------------------------------------

    def _make_world_provider(self, life_day, minute):
        weather_code = weather_service.at(life_day, minute)

        def with_world(fn):
            with self.lock:
                return fn(World(
                    time_minutes=minute,
                    agent_locations={a.name: a.current_location for a in self.agents},
                    unread_counts=mailbox_module.mailbox.unread_counts(),
                    balances=economy_module.economy.balances(),
                    weather_code=weather_code,
                    life_day=life_day,
                ))
        return with_world

    # --- 一次决策 ---------------------------------------------------

    def _decide(self, agent, life_day, minute):
        state = load_agent_state(agent.name)
        triggers = evaluate_agent_triggers(state)
        time_text = format_clock(minute)
        started = time.monotonic()

        decision, steps = run_decision_loop(
            agent,
            internal_state=state,
            triggers=triggers,
            day_number=life_day,
            time_text=time_text,
            current_location=agent.current_location,
            last_action=getattr(agent, "_last_action_text", None),
            with_world=self._make_world_provider(life_day, minute),
        )
        elapsed = time.monotonic() - started

        # 动作完成：推进需求锚点，并记进记忆（和真实路由做的一样）。
        complete_agent_action(
            agent.name,
            location_name=decision["destination"],
            action_text=decision["action"],
            elapsed_game_minutes=decision["duration_minutes"],
            day=life_day,
            time=time_text,
        )
        agent._last_action_text = decision["action"]

        with self.lock:
            self.decisions += 1
            self.llm_calls += max(1, len(steps))
            self.latencies.append(elapsed)
            self.steps_per_turn.append(len(steps))
            self.sources[decision.get("source", "?")] += 1
            for entry in steps:
                self.tool_calls[entry["tool"]] += 1
                self.by_agent[agent.name][entry["tool"]] += 1
                if not entry["ok"]:
                    self.rejections[entry.get("reason") or "?"] += 1

        self._report(agent, life_day, minute, decision, steps, elapsed)
        return decision

    def _report(self, agent, life_day, minute, decision, steps, elapsed):
        if not self.verbose:
            return
        with self.print_lock:
            print(f"\nday {life_day}  {format_clock(minute):>8}  {agent.name}"
                  f"   [{elapsed:.1f}s]")
            for index, entry in enumerate(steps, 1):
                mark = "   " if entry["ok"] else "[x] "
                thought = (entry.get("thought") or "").strip()
                print(f"   {index}. {mark}{entry['tool']}({entry['summary']})")
                if thought:
                    print(f"        thought: {thought}")
                print(f"        -> {entry['observation'][:160]}")
            if decision.get("source") != "llm":
                print(f"      !! fell back ({decision.get('source')})")
            sys.stdout.flush()

    # --- 一天 -------------------------------------------------------

    def _run_day(self, life_day):
        next_at = {
            agent.name: WAKE_MINUTE + index * WAKE_STAGGER
            for index, agent in enumerate(self.agents)
        }
        by_name = {agent.name: agent for agent in self.agents}

        codes = weather_service.for_day(life_day)
        print(f"\n{'=' * 78}")
        print(f"DAY {life_day}   weather: "
              f"{describe(codes[9])} at 9am, {describe(codes[15])} at 3pm"
              f"   (source: {weather_service.source_for(life_day)})")
        print(f"{'=' * 78}")

        while True:
            if self.max_decisions and self.decisions >= self.max_decisions:
                return "limit"

            # 睡到明天的人已经退出今天了——只在还醒着的人里挑最早的。
            awake = {name: when for name, when in next_at.items() if when < DAY_END}
            if not awake:
                return "everyone turned in"
            due = min(awake.values())
            if due >= DAY_END:
                return "day over"

            # 同一时刻到点的人并发决策——他们会真的争同一个座位。
            batch = [name for name, when in awake.items() if when == due]
            results = {}

            def drive(name):
                try:
                    results[name] = self._decide(by_name[name], life_day, due)
                except Exception as error:            # noqa: BLE001
                    with self.print_lock:
                        print(f"   !! {name} decision raised: {error!r}")

            if len(batch) == 1:
                drive(batch[0])
            else:
                threads = [threading.Thread(target=drive, args=(name,)) for name in batch]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join()

            for name in batch:
                decision = results.get(name)
                next_at[name] = due + (decision["duration_minutes"] if decision else 60)

    def _end_day(self, life_day):
        """跨天：补货、社保、反思。反思会更新 persona，进而影响第二天的决策——
        这是唯一必须跨天才观察得到的链路。"""
        print(f"\n--- end of day {life_day} ---")
        economy_module.economy.restock_daily()
        paid = economy_module.economy.pay_benefit(life_day + 1, self.names)
        print(f"  restocked unowned shops; benefit paid: {paid.get('paid')}")

        for agent in self.agents:
            reflection = Reflection(self.memory, agent.name)
            _, answer = reflection.generate_reflection(life_day=life_day)
            self.llm_calls += 1
            if answer:
                print(f"  {agent.name}: {str(answer)[:110]}")

    # --- 入口 -------------------------------------------------------

    def run(self):
        started = time.monotonic()
        try:
            for life_day in range(1, self.days + 1):
                self.memory.set_life_day(life_day, self.names)
                reason = self._run_day(life_day)
                if reason == "limit":
                    print("\n[stopped: decision limit reached]")
                    break
                if life_day < self.days:
                    self._end_day(life_day)
        finally:
            self._summary(time.monotonic() - started)
            shutil.rmtree(self.sandbox, ignore_errors=True)

    def _summary(self, wall_seconds):
        print(f"\n\n{'=' * 78}")
        print("SUMMARY")
        print(f"{'=' * 78}")
        print(f"  decisions            {self.decisions}")
        print(f"  llm calls            {self.llm_calls}")
        print(f"  wall clock           {wall_seconds / 60:.1f} min")
        if self.latencies:
            ordered = sorted(self.latencies)
            print(f"  per-decision latency median {ordered[len(ordered)//2]:.1f}s  "
                  f"p90 {ordered[int(len(ordered)*0.9)]:.1f}s")
        if self.steps_per_turn:
            print(f"  steps per turn       avg {sum(self.steps_per_turn)/len(self.steps_per_turn):.2f}  "
                  f"max {max(self.steps_per_turn)}")

        print("\n  tool usage")
        total = sum(self.tool_calls.values()) or 1
        from tools import TOOL_REGISTRY
        for name in TOOL_REGISTRY:
            count = self.tool_calls.get(name, 0)
            bar = "#" * int(40 * count / total)
            flag = "" if count else "   <- never used"
            print(f"    {name:15s} {count:>4}  {bar}{flag}")

        if self.rejections:
            print("\n  rejections")
            for reason, count in self.rejections.most_common():
                print(f"    {reason:22s} {count}")
        else:
            print("\n  rejections           none — the world never said no")

        print("\n  decision source")
        for source, count in self.sources.most_common():
            print(f"    {source:22s} {count}")

        self._scenario_report()

        print(f"\n  traces written to")
        print(f"    {os.environ['ACTION_TRACE_FILE']}")
        print(f"    {os.environ['LLM_TRACE_FILE']}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=2)
    parser.add_argument("--max-decisions", type=int, default=None,
                        help="先测速用：跑够这么多次决策就停")
    parser.add_argument("--scenario", choices=["errand"], default=None,
                        help="埋一个起因，逼出协作链（自然跑永远跑不出协作）")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    from config import LLM_API_KEY, LLM_MODEL
    if not LLM_API_KEY:
        print("No LLM_API_KEY — set it in backend/.env first.")
        return 1
    print(f"model: {LLM_MODEL}   days: {args.days}")

    DryRun(days=args.days, max_decisions=args.max_decisions,
           verbose=not args.quiet, scenario=args.scenario).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
