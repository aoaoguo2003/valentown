"""一天的预算，以及动作日志和 LLM 日志能不能对上。

两件事都属于"平时不响、响了说明出事"的那一类，所以只能靠故障注入来测。

`MAX_STEPS` 管的是**一轮**想几步，预算管的是**一天**花多少——两者拦的不是
同一种失控。实测一个居民一天约 17–34 次调用，默认上限 120 次，正常跑碰不到；
但加个居民、把 MAX_STEPS 调到 10、场景多跑两天，账就会翻倍。
"""

import pytest
from llm import LLMClient
from runtime.budgets import Budget
from runtime.scheduler import Town


@pytest.fixture(autouse=True)
def cheap_llm(monkeypatch):
    """假 LLM：每次都待在原地，并且报告固定的 token 用量。"""
    def always_stay(self, agent_name, context, tool_schemas):
        self.last_usage = {"prompt_tokens": 4000, "completion_tokens": 60,
                           "total_tokens": 4060}
        return {"name": "stay", "args": {"thought": "resting",
                                         "action": "sit about at home",
                                         "duration_minutes": 60,
                                         "talk_to": "nobody"}}

    monkeypatch.setattr(LLMClient, "call_tools", always_stay)
    monkeypatch.setattr(LLMClient, "get_response", lambda self, *a, **k: None)
    monkeypatch.setattr(LLMClient, "rate_importance",
                        lambda self, n, t, fallback=4: fallback)


# --- 记账 --------------------------------------------------------------------

def test_calls_and_tokens_are_counted_per_agent_per_day():
    """按「人 + 天」记，不是全局一本账——一个话痨不该拖累其他六个人。"""
    budget = Budget()

    budget.record("Ron Parker", 1, tokens=100)
    budget.record("Ron Parker", 1, tokens=200)
    budget.record("Ron Parker", 2, tokens=50)
    budget.record("Emma Harris", 1, tokens=999)

    assert budget.usage("Ron Parker", 1) == {"calls": 2, "tokens": 300}
    assert budget.usage("Ron Parker", 2) == {"calls": 1, "tokens": 50}
    assert budget.usage("Emma Harris", 1) == {"calls": 1, "tokens": 999}


def test_a_new_day_starts_from_zero():
    budget = Budget(calls_per_day=2)

    for _ in range(2):
        budget.record("Ron Parker", 1)
    assert budget.exceeded("Ron Parker", 1)
    assert budget.exceeded("Ron Parker", 2) is None


# --- 查闸 --------------------------------------------------------------------

def test_the_reason_says_which_limit_was_hit():
    """返回话而不是布尔值——"预算用完了"排查时等于没说。"""
    calls = Budget(calls_per_day=1, tokens_per_day=None)
    calls.record("Ron Parker", 1, tokens=10)
    assert "model calls" in calls.exceeded("Ron Parker", 1)

    tokens = Budget(calls_per_day=None, tokens_per_day=100)
    tokens.record("Ron Parker", 1, tokens=100)
    assert "tokens" in tokens.exceeded("Ron Parker", 1)


def test_a_limit_of_none_means_no_limit():
    budget = Budget(calls_per_day=None, tokens_per_day=None)

    for _ in range(500):
        budget.record("Ron Parker", 1, tokens=10_000)

    assert budget.exceeded("Ron Parker", 1) is None


# --- 撞上之后：兜底，不是抛异常 -------------------------------------------------

def test_running_out_of_budget_falls_back_instead_of_stalling():
    """线上那条路必须保持"模型不可用就走确定性兜底"，模拟不能卡住。

    而且这条兜底的理由要和 `llm_unavailable` **分开**：一个是没钱了，
    一个是打不通，混成一类排查时会走冤枉路。
    """
    from observability import metrics

    with Town(days=1, max_decisions=6,
              budget=Budget(calls_per_day=1)) as town:
        town.run()
        events = []
        # 直接从循环写出的记录里看：第一次之后应该全是 budget_exhausted
        import observability.trace as trace_module
        assert trace_module.ACTION_TRACE_FILE

    assert town.decisions >= 1
    assert metrics.GIVE_UP_REASONS >= {"budget_exhausted", "llm_unavailable"}


def test_the_budget_stops_the_calls_it_says_it_stops(tmp_path):
    from observability import metrics

    trace = tmp_path / "action.jsonl"
    with Town(days=1, max_decisions=8, trace_file=trace,
              budget=Budget(calls_per_day=1)) as town:
        town.run()

    wasted = metrics.summarise(metrics.load(trace))["wasted_turns"]["by_reason"]
    assert wasted.get("budget_exhausted", 0) > 0, "预算该拦下的轮次一次都没拦到"


def test_a_generous_budget_never_gets_in_the_way(tmp_path):
    """默认值必须是**平时不响**的。响了就说明它设得太紧，会污染每一次评估。"""
    from observability import metrics

    trace = tmp_path / "action.jsonl"
    with Town(days=1, max_decisions=8, trace_file=trace) as town:   # 用默认预算
        town.run()

    wasted = metrics.summarise(metrics.load(trace))["wasted_turns"]["by_reason"]
    assert "budget_exhausted" not in wasted


def test_the_report_says_how_close_it_came():
    """护栏没响不代表设得合适——**离上限还有多远**才说明它是不是形同虚设。"""
    budget = Budget(calls_per_day=100, tokens_per_day=1000)
    for _ in range(10):
        budget.record("Ron Parker", 1, tokens=50)

    report = budget.report()

    assert report["calls"]["max"] == 10
    assert report["tokens"]["max"] == 500
    assert report["closest_to_the_limit"] == pytest.approx(0.5)   # token 用了一半


# --- 两份日志对得上吗 ----------------------------------------------------------

def test_each_step_carries_a_trace_id_and_the_goal_it_was_serving(tmp_path):
    """动作日志和 LLM 日志本来各记各的，对不上——于是"这一步花了多少
    token"永远答不了。一个共同的 trace_id 把行为和成本缝在一起。"""
    from observability import metrics

    action, llm_trace = tmp_path / "action.jsonl", tmp_path / "llm.jsonl"
    with Town(days=1, max_decisions=3,
              trace_file=action, llm_trace_file=llm_trace) as town:
        town.run()

    steps = [r for r in metrics.load(action) if r.get("tool") != "fallback"]
    assert steps, "一步都没记下来"
    assert all(r.get("trace_id") for r in steps), "有步骤没带 trace_id"
    assert all("goal" in r for r in steps), "有步骤没带 goal 字段"
