"""调度器的测试：隔离、还原、消融、早停。全部用假 LLM，不打一次网络。

重点是**隔离与还原**。一次评估会在同一个进程里连跑几十座小镇
（场景 x 消融 x 重复），漏还原一处，第二座小镇就继承了第一座的世界——
而这不会报错，只会让第二格的数字变成假的。这类 bug 只能靠测试挡。
"""

import agents.state as agent_state
import observability.trace as trace_module
import pytest
import tools
import world.economy as economy_module
import world.goals as goals_module
import world.mailbox as mailbox_module
import world.weather as weather_module
from llm import LLMClient
from memory.persona_store import persona_store
from runtime.scheduler import Town


@pytest.fixture(autouse=True)
def no_real_llm(monkeypatch):
    """七个居民各自持有一个 LLMClient，所以要在类上打桩。

    脚本很简单：每个人都待在原地一小时。这里测的是调度器，不是决策质量。
    """
    def always_stay(self, agent_name, context, tool_schemas):
        return {
            "name": "stay",
            "args": {
                "thought": "nothing pressing",
                "action": "sit about at home",
                "duration_minutes": 60,
                "talk_to": "nobody",
            },
        }

    monkeypatch.setattr(LLMClient, "call_tools", always_stay)
    monkeypatch.setattr(LLMClient, "get_response", lambda self, *a, **k: None)
    monkeypatch.setattr(LLMClient, "rate_importance",
                        lambda self, name, text, fallback=4: fallback)


def _live_globals():
    """所有被 Town 换掉的名字，用来断言进出前后一致。"""
    return (
        agent_state.STATE_DIR,
        economy_module.economy,
        goals_module.goal_store,
        mailbox_module.mailbox,
        persona_store.persona_dir,
        weather_module.WEATHER_ENABLED,
        weather_module.weather_service,
        tools.function_schemas,
        tools.get_tool,
    )


# --- 隔离与还原 --------------------------------------------------------------

def test_the_town_puts_every_global_back_when_it_leaves():
    before = _live_globals()

    with Town(days=1, tools_disabled={"send_mail"}) as town:
        during = _live_globals()
        assert during != before, "进了 with 块却什么都没换，隔离是假的"

    assert _live_globals() == before, "出块后有名字没还原"


def test_the_town_puts_things_back_even_when_the_body_raises():
    before = _live_globals()

    with pytest.raises(RuntimeError):
        with Town(days=1):
            raise RuntimeError("boom")

    assert _live_globals() == before


def test_seeding_inside_a_town_never_touches_the_real_world():
    real = economy_module.economy
    real_balance = real.balance("Emma Harris")

    with Town(days=1) as town:
        town.economy.seed(balances={"Emma Harris": 999})
        assert town.economy.balance("Emma Harris") == 999

    assert economy_module.economy is real
    assert real.balance("Emma Harris") == real_balance


def test_two_towns_in_a_row_do_not_leak_into_each_other():
    """评估会连跑几十座小镇。第二座必须是干净的。"""
    with Town(days=1) as first:
        first.economy.seed(balances={"Emma Harris": 999})
        first.mailbox.send(sender="Gavin Harris", recipient="Emma Harris",
                           subject="hello", body="hello", life_day=1, time_text="7:00 AM")

    with Town(days=1) as second:
        assert second.economy.balance("Emma Harris") != 999
        assert second.mailbox.unread_counts().get("Emma Harris", 0) == 0


def test_personas_are_isolated_too():
    """反思会写 persona。它曾经是隔离里唯一的漏洞——``dry_run`` 宣称
    一个字节都不碰真实存档，而每晚的反思都写进了真实的 agent_personas/。

    ⚠️ persona_store 换的是**对象身上的目录**：``agents/agent.py`` 和
    ``memory/reflection.py`` 都在模块顶层绑死了那个对象，换模块上的名字
    对它们无效。
    """
    real_dir = persona_store.persona_dir

    with Town(days=1) as town:
        assert persona_store.persona_dir != real_dir
        assert persona_store.persona_dir.parent == town.sandbox

    assert persona_store.persona_dir == real_dir


# --- 消融 --------------------------------------------------------------------

def test_disabling_a_tool_removes_it_from_the_schema_and_the_registry():
    """两处都要摘。

    只摘 schema 的话，模型偶尔会凭记忆编出一个已摘掉的名字并成功执行——
    那消融就漏了，而漏的后果不是报错，是消融组跑出和基线一模一样的数字，
    看上去像"这个能力本来就没用"。
    """
    with Town(days=1, tools_disabled={"send_mail", "accept_meeting"}):
        names = {schema["function"]["name"]
                 for schema in tools.function_schemas("Ron Parker")}
        assert "send_mail" not in names
        assert "accept_meeting" not in names
        assert "move_to" in names

        assert tools.get_tool("send_mail") is None          # 硬调也拿不到
        assert tools.get_tool("move_to") is not None

    assert tools.get_tool("send_mail") is not None          # 出块即还原


def test_no_ablation_leaves_the_toolbox_alone():
    with Town(days=1) as town:
        assert len(tools.function_schemas("Ron Parker")) == len(
            [name for name in tools.TOOL_REGISTRY
             if tools.TOOL_REGISTRY[name].is_eligible("Ron Parker")])


# --- 天气必须钉死 --------------------------------------------------------------

def test_weather_is_deterministic_so_two_runs_are_comparable():
    """天气是真实的伦敦数据。今天下雨明天不下，同一个场景两次跑就不可比了
    ——那对比的是天气，不是模型。"""
    with Town(days=1):
        first = weather_module.weather_service.for_day(1)
        assert weather_module.weather_service.source_for(1) == "disabled"

    with Town(days=1):
        second = weather_module.weather_service.for_day(1)

    assert first == second


def test_live_weather_can_be_asked_for_explicitly():
    with Town(days=1, deterministic_weather=False):
        assert weather_module.WEATHER_ENABLED is True


# --- 跑起来 ------------------------------------------------------------------

def test_the_decision_limit_stops_the_run():
    with Town(days=1, max_decisions=3) as town:
        reason = town.run()

    assert reason == "decision limit"
    # 同一时刻到点的人是**并发一批**跑完的，所以会略微超出上限——
    # 这是护栏不是配额，超一批不影响它挡住失控。
    assert 3 <= town.decisions <= 3 + 7


def test_stop_when_ends_the_run_as_soon_as_the_goal_is_reached():
    calls = {"n": 0}

    def judge_says_done():
        calls["n"] += 1
        return calls["n"] >= 2

    with Town(days=1, max_decisions=200, stop_when=judge_says_done) as town:
        reason = town.run()

    assert reason == "goal reached"
    assert calls["n"] == 2
    assert town.decisions < 200


def test_every_decision_reaches_the_hook_and_the_trace(tmp_path):
    trace = tmp_path / "action.jsonl"
    seen = []

    with Town(days=1, max_decisions=2, trace_file=trace,
              on_decision=seen.append) as town:
        town.run()

    assert seen, "on_decision 一次都没被调到"
    assert {event["agent"].name for event in seen} <= set(town.names)
    assert trace.exists(), "动作日志没写到 Town 指定的文件里"

    from observability import metrics
    summary = metrics.summarise(metrics.load(trace))
    assert summary["turns"] == len(seen)
    assert summary["convergence"].get("stay") == len(seen)


def test_the_trace_file_setting_is_restored():
    original = trace_module.ACTION_TRACE_FILE

    with Town(days=1, trace_file="somewhere/else.jsonl"):
        assert trace_module.ACTION_TRACE_FILE == "somewhere/else.jsonl"

    assert trace_module.ACTION_TRACE_FILE == original


def test_max_steps_can_be_forced_down_for_the_single_step_ablation():
    """`--ablate single-step` 就是把上限压到 1：被拒直接兜底，
    没有第二次机会——这正是改造前那一版的形态。"""
    with Town(days=1, max_decisions=1, max_steps=1) as town:
        town.run()

    assert town.decisions >= 1
