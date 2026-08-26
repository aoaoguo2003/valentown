"""调度器：把七个居民放进一座隔离的小镇里，按时钟跑若干天。

这是 ``scripts/dry_run.py`` 和 ``evals/runner.py`` 共用的引擎。两边只有
"跑完之后拿它干什么"不同——一个打详细日志给人看，一个对着判据打分——
**跑的过程必须是同一份代码**。上一次同一个东西两处装配的代价，规则 4 记着：
给一处加字段，另一处就开始说谎，一次十七分钟的跑出来的数字全是废的。

## 调度

每个居民有自己的"下次决策时刻"，每轮挑**最早的那一批**来跑；同一时刻到点
的人**真的开线程并发决策**。这和前端 ``game.js`` 的做法一致，也是抢座位、
邮件往返、天气变化能自然发生的前提——各跑各的时间线，多智能体互动就全测
不出来了。

## 隔离

进 ``with`` 块时把每一处全局状态指向临时目录（存档、天气、日志路径、
工具注册表），出块时**原样还原**。还原这一步
是给评估用的：一次评估会在同一个进程里连跑几十座小镇（场景 x 消融 x 重复），
漏还原一处，第二座小镇就继承了第一座的世界。

⚠️ 其中 ``persona_store`` 是**换属性**而不是换对象：``agents/agent.py`` 和
``memory/reflection.py`` 都在模块顶层 ``from memory.persona_store import
persona_store``，加载时就绑死了那个对象，换掉模块上的名字对它们无效。
换对象身上的目录，两边就都跟着走了。

（这个缺口是抽这个模块时才发现的：``dry_run`` 一直宣称"一个字节都不碰真实
存档"，而每晚的反思其实都写进了真实的 ``memory/agent_personas/``。）
"""

import shutil
import tempfile
import threading
import time
from pathlib import Path

import agents.state as agent_state
import observability.trace as trace_module
import tools as tools_module
import world.economy as economy_module
import world.events as events_module
import world.goals as goals_module
import world.mailbox as mailbox_module
import world.weather as weather_module
from agents.agent import (
    AdamHarris,
    ArthurMorgan,
    EllaParker,
    EmmaHarris,
    GavinHarris,
    MiaThompson,
    RonParker,
)
from llm import LLMClient
from memory.memory_system import MemorySystem
from memory.persona_store import persona_store
from memory.reflection import Reflection
from runtime.agent_runtime import run_decision_loop
from runtime.budgets import Budget
from world.clock import format_clock
from world.snapshot import snapshot

WAKE_MINUTE = 6 * 60 + 30       # 第一个人起床的时刻
WAKE_STAGGER = 10               # 起床时间错开，和前端一致
DAY_END = 24 * 60               # 睡过这条线的人今天就不再决策了
DEFAULT_DURATION = 60           # 决策抛异常时，假定他花了一小时

AGENT_CLASSES = [
    (RonParker, "Ron_home.Living_room"),
    (EllaParker, "Ella_home.Living_room"),
    (EmmaHarris, "Emma_home.Living_room"),
    (GavinHarris, "Gavin_home.Living_room"),
    (AdamHarris, "Adam_home.Living_room"),
    (MiaThompson, "Mia_home.Living_room"),
    (ArthurMorgan, "Arthur_home.Living_room"),
]


class Town:
    """一座隔离的小镇。用 ``with`` 进出，出来时世界原样。

    ``on_decision(event)``   每做完一次决策调一次，用来打日志。
    ``stop_when()``          每批决策后问一次，返回 True 就收工（评估的早停）。
    ``tools_disabled``       摘掉这些工具——消融实验就靠它。
    ``filter_tools``         此刻用不了的工具不进 schema，改成上下文里一行。
    """

    def __init__(self, *, days=1, max_decisions=None, max_steps=None,
                 tools_disabled=(), filter_tools=False, omit_context=(),
                 deterministic_weather=True, reflect=True,
                 trace_file=None, llm_trace_file=None,
                 budget=None, on_decision=None, stop_when=None):
        self.days = days
        self.max_decisions = max_decisions
        self.max_steps = max_steps
        self.tools_disabled = frozenset(tools_disabled)
        self.filter_tools = filter_tools
        self.omit_context = tuple(omit_context)
        # 默认带一本账。正常跑碰不到上限——留着是为了跑完能看
        # **离上限还有多远**：护栏没响不代表设得合适。
        self.budget = Budget() if budget is None else budget
        self.deterministic_weather = deterministic_weather
        self.reflect = reflect
        self.trace_file = trace_file
        self.llm_trace_file = llm_trace_file
        self.on_decision = on_decision
        self.stop_when = stop_when

        self.sandbox = None
        self.lock = threading.Lock()
        self.decisions = 0
        self.llm_calls = 0
        self.latencies = []
        self.stopped_because = None
        self._restore = []

    # --- 隔离 -----------------------------------------------------------

    def _swap(self, module, name, value):
        """换掉模块上的一个名字，并记下怎么还原。"""
        self._restore.append((module, name, getattr(module, name)))
        setattr(module, name, value)

    def __enter__(self):
        self.sandbox = Path(tempfile.mkdtemp(prefix="valentown-town-"))

        self._swap(agent_state, "STATE_DIR", self.sandbox / "agent_states")
        self._swap(goals_module, "goal_store",
                   goals_module.GoalStore(path=self.sandbox / "goals.json"))
        self._swap(economy_module, "economy",
                   economy_module.Economy(path=self.sandbox / "economy.json"))
        self._swap(mailbox_module, "mailbox",
                   mailbox_module.Mailbox(path=self.sandbox / "mailboxes.json"))
        self._swap(events_module, "event_log", events_module.EventLog())
        # persona 换的是对象身上的目录，不是模块上的名字——见模块开头。
        self._swap(persona_store, "persona_dir", self.sandbox / "personas")

        if self.deterministic_weather:
            # 天气是真实的伦敦数据。今天下雨明天不下，同一个场景两次跑就
            # 不可比了——那对比的是天气，不是模型。关掉真实调用之后走降级
            # 路径，它用 life_day 做种子，同一天永远是同一种天气。
            self._swap(weather_module, "WEATHER_ENABLED", False)
            self._swap(weather_module, "weather_service", weather_module.WeatherService())

        if self.trace_file:
            # 每座小镇写自己的动作日志，评估才能一格一格地算指标。
            self._swap(trace_module, "ACTION_TRACE_FILE", str(self.trace_file))
        if self.llm_trace_file:
            # 成本也要能按格拆：token 和延迟在另一份日志里。
            self._swap(trace_module, "LLM_TRACE_FILE", str(self.llm_trace_file))

        if self.tools_disabled:
            self._disable_tools()

        self._build_agents()
        return self

    def __exit__(self, *exc):
        for module, name, original in reversed(self._restore):
            setattr(module, name, original)
        self._restore.clear()
        if self.sandbox:
            shutil.rmtree(self.sandbox, ignore_errors=True)
        return False

    def _disable_tools(self):
        """摘掉几件工具：模型看不见它们，硬调也执行不了。

        两处都要摘。只摘 schema 的话，模型偶尔会凭记忆编出一个已摘掉的
        名字并成功执行——那消融就漏了，而漏的后果不是报错，是消融组跑出
        和基线一样的数字。
        """
        disabled = self.tools_disabled
        real_schemas = tools_module.function_schemas
        real_get = tools_module.get_tool

        def schemas(agent_name=None):
            return [
                schema for schema in real_schemas(agent_name)
                if schema["function"]["name"] not in disabled
            ]

        def get(name):
            return None if name in disabled else real_get(name)

        self._swap(tools_module, "function_schemas", schemas)
        self._swap(tools_module, "get_tool", get)

    def _build_agents(self):
        self.memory = MemorySystem(retention_days=15, memory_dir=self.sandbox / "memories")
        self.agents = [cls(self.memory, home) for cls, home in AGENT_CLASSES]
        self.names = [agent.name for agent in self.agents]
        self.memory.initialize_agents(self.names)
        agent_state.ensure_agent_state_files(self.names)

    # --- 世界服务的句柄：场景的 seed / judge 用它 -------------------------

    @property
    def economy(self):
        return economy_module.economy

    @property
    def goals(self):
        return goals_module.goal_store

    @property
    def mailbox(self):
        return mailbox_module.mailbox

    # --- 世界快照 -------------------------------------------------------

    def _make_world_provider(self, life_day, minute):
        # 天气先预热，免得把一次网络往返带进锁里。
        weather_module.weather_service.at(life_day, minute)
        # 事件要盖时间戳，而世界服务不知道现在几点。
        events_module.event_log.set_clock(life_day, minute)

        def with_world(fn):
            with self.lock:
                # 和线上走同一个 snapshot()：曾经这里自己拼 World，
                # 结果新增 holdings 字段时漏了，整整一次跑的数字全是废的。
                return fn(snapshot(
                    agent_locations={a.name: a.current_location for a in self.agents},
                    time_minutes=minute,
                    life_day=life_day,
                ))
        return with_world

    # --- 一次决策 -------------------------------------------------------

    def _decide(self, agent, life_day, minute):
        state = agent_state.load_agent_state(agent.name)
        triggers = agent_state.evaluate_agent_triggers(state)
        time_text = format_clock(minute)
        started = time.monotonic()

        extra = {"max_steps": self.max_steps} if self.max_steps else {}
        decision, steps = run_decision_loop(
            agent,
            internal_state=state,
            triggers=triggers,
            day_number=life_day,
            time_text=time_text,
            current_location=agent.current_location,
            last_action=getattr(agent, "_last_action_text", None),
            with_world=self._make_world_provider(life_day, minute),
            filter_tools=self.filter_tools,
            omit_context=self.omit_context,
            budget=self.budget,
            **extra,
        )
        elapsed = time.monotonic() - started

        # 动作完成：推进需求锚点，并记进记忆（和真实路由做的一样）。
        agent_state.complete_agent_action(
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

        if self.on_decision:
            self.on_decision({
                "agent": agent, "life_day": life_day, "minute": minute,
                "time_text": time_text, "decision": decision,
                "steps": steps, "elapsed": elapsed,
            })
        return decision

    # --- 一天 -----------------------------------------------------------

    def _run_day(self, life_day):
        next_at = {
            agent.name: WAKE_MINUTE + index * WAKE_STAGGER
            for index, agent in enumerate(self.agents)
        }
        by_name = {agent.name: agent for agent in self.agents}

        while True:
            if self.max_decisions and self.decisions >= self.max_decisions:
                return "decision limit"

            # 睡到明天的人已经退出今天了——只在还醒着的人里挑最早的。
            awake = {name: when for name, when in next_at.items() if when < DAY_END}
            if not awake:
                return "everyone turned in"
            due = min(awake.values())

            # 同一时刻到点的人并发决策——他们会真的争同一个座位。
            batch = [name for name, when in awake.items() if when == due]
            results = {}
            errors = {}

            def drive(name):
                try:
                    results[name] = self._decide(by_name[name], life_day, due)
                except Exception as error:            # noqa: BLE001
                    errors[name] = error

            if len(batch) == 1:
                drive(batch[0])
            else:
                threads = [threading.Thread(target=drive, args=(name,)) for name in batch]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join()

            for name, error in errors.items():
                print(f"   !! {name} decision raised: {error!r}")

            for name in batch:
                decision = results.get(name)
                next_at[name] = due + (
                    decision["duration_minutes"] if decision else DEFAULT_DURATION)

            # 账户级故障（余额、密钥、权限）不会自己好。继续跑只会把
            # 剩下的轮次全变成兜底，产出一份看起来像"模型很差"的假数据。
            if LLMClient.fatal_error:
                return "llm unavailable"

            # 早停：判据一过就收工。省时间，而且"用了几次决策"本身是个指标。
            if self.stop_when and self.stop_when():
                return "goal reached"

    def _end_day(self, life_day):
        """跨天：补货、社保、反思。反思会更新 persona，进而影响第二天的
        决策——这是唯一必须跨天才观察得到的链路。"""
        economy_module.economy.restock_daily()
        paid = economy_module.economy.pay_benefit(life_day + 1, self.names)

        summaries = []
        if self.reflect:
            for agent in self.agents:
                _, answer = Reflection(self.memory, agent.name).generate_reflection(
                    life_day=life_day)
                self.llm_calls += 1
                if answer:
                    summaries.append((agent.name, str(answer)))
        return {"benefit_paid": paid.get("paid"), "reflections": summaries}

    # --- 入口 -----------------------------------------------------------

    def run(self, on_day_start=None, on_day_end=None):
        """跑完，返回结束原因。必须在 ``with`` 块里调用。"""
        assert self.sandbox is not None, "Town 必须在 with 块里使用"
        started = time.monotonic()
        reason = "finished"

        for life_day in range(1, self.days + 1):
            self.memory.set_life_day(life_day, self.names)
            if on_day_start:
                on_day_start(life_day)

            reason = self._run_day(life_day)
            if reason in ("decision limit", "goal reached"):
                break
            if life_day < self.days:
                report = self._end_day(life_day)
                if on_day_end:
                    on_day_end(life_day, report)

        self.wall_seconds = time.monotonic() - started
        self.stopped_because = reason
        return reason
