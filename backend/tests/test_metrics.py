"""指标层的测试：喂假日志进去，断言算出来的数字是对的。

一行 LLM 调用都不打，一分钱不花——这正是先做指标层的理由：它只读日志，
写错了也弄不坏任何东西，而对不对当场就能验。

最后两个测试是**对账**：指标模块为了能独立跑，自己抄了一份工具分类和拒绝
理由清单；这两个测试拿真注册表和真源码来核对，谁先走散谁红。
"""

import json
import re
from pathlib import Path

from observability import metrics


def _rec(agent, step, tool, ok=True, reason=None, summary=""):
    """造一条动作日志记录，字段和 log_action_event 写出来的一致。"""
    return {
        "ts": "2026-08-25T10:00:00.000",
        "agent_name": agent,
        "life_day": 1,
        "time_text": "10:00 AM",
        "step": step,
        "tool": tool,
        "summary": summary,
        "thought": "because",
        "ok": ok,
        "reason": reason,
        "observation": "something happened",
    }


# --- 切轮 -------------------------------------------------------------------

def test_turns_are_split_per_agent_not_per_line():
    # 七个居民并发决策，写的是同一个文件，记录天然交错。不先按人分组就切，
    # 会把两个人的步骤缝成一轮——第一版就是这么算出"一轮 11 步"的。
    records = [
        _rec("Ron Parker", 0, "check_stock"),
        _rec("Emma Harris", 0, "recall"),
        _rec("Ron Parker", 1, "move_to"),
        _rec("Emma Harris", 1, "move_to"),
    ]

    turns = metrics.split_turns(records)

    assert len(turns) == 2
    assert [len(turn) for turn in turns] == [2, 2]
    assert metrics.summarise(records)["steps_per_turn"]["max"] == 2


def test_a_second_turn_starts_at_step_zero():
    records = [
        _rec("Ron Parker", 0, "recall"),
        _rec("Ron Parker", 1, "move_to"),
        _rec("Ron Parker", 0, "stay"),
    ]

    assert [len(turn) for turn in metrics.split_turns(records)] == [2, 1]


# --- 拒绝的三种含义 ----------------------------------------------------------

def test_rejections_split_into_model_faults_and_the_world_saying_no():
    records = [
        _rec("Ron Parker", 0, "buy", ok=False, reason="unknown_item"),        # 参数填错
        _rec("Ron Parker", 1, "buy", ok=False, reason="insufficient_funds"),  # 世界说不行
        _rec("Ron Parker", 2, "recall", ok=False, reason="already_known"),    # 循环拦下
        _rec("Ron Parker", 3, "stay"),
    ]

    summary = metrics.summarise(records)

    # 模型的错 = 参数填错 + 循环拦下
    assert summary["invalid_calls"]["count"] == 2
    assert summary["invalid_calls"]["arguments"] == {"unknown_item": 1}
    assert summary["invalid_calls"]["guard"] == {"already_known": 1}

    # 钱不够不是错，那是环境在工作
    assert summary["environment_refusals"]["count"] == 1
    assert summary["environment_refusals"]["by_reason"] == {"insufficient_funds": 1}


def test_an_unheard_of_reason_is_reported_not_swallowed():
    # 将来谁加了个新的拒绝理由却忘了归类，报告要吵起来，
    # 而不是把它默默算进"世界说不行"里稀释掉真实数字。
    records = [
        _rec("Ron Parker", 0, "buy", ok=False, reason="struck_by_lightning"),
        _rec("Ron Parker", 1, "stay"),
    ]

    summary = metrics.summarise(records)

    assert summary["unclassified"]["reasons"] == {"struck_by_lightning": 1}
    assert summary["environment_refusals"]["count"] == 0
    assert summary["invalid_calls"]["count"] == 0
    assert "分类没跟上代码" in metrics.format_report(summary)


def test_a_made_up_tool_name_is_not_a_classification_gap():
    # 模型真的编过一个叫 think 的工具。日志里出现注册表没有的名字有两种
    # 可能，unknown_tool 把"模型编的"认了出来，剩下的才该报警。
    records = [
        _rec("Ron Parker", 0, "think", ok=False, reason="unknown_tool"),
        _rec("Ron Parker", 1, "stay"),
    ]

    summary = metrics.summarise(records)

    assert summary["invented_tools"] == {"think": 1}
    assert summary["unclassified"]["tools"] == []
    assert "分类没跟上代码" not in metrics.format_report(summary)


# --- 被拒之后做了什么 --------------------------------------------------------

def test_replanning_tells_a_new_plan_from_hitting_the_same_wall():
    records = [
        # 换招：被拒之后换了个目的地
        _rec("Ron Parker", 0, "move_to", ok=False, reason="closed",
             summary="destination='Pharmacy.Medicine_shelf'"),
        _rec("Ron Parker", 1, "move_to", summary="destination='Park.Bench'"),

        # 撞墙：一模一样的调用又来一次，然后才换招
        _rec("Emma Harris", 0, "buy", ok=False, reason="out_of_stock", summary="item='milk'"),
        _rec("Emma Harris", 1, "buy", ok=False, reason="out_of_stock", summary="item='milk'"),
        _rec("Emma Harris", 2, "stay"),

        # 没机会：被拒之后步数就用完了，这不怪模型
        _rec("Mia Thompson", 0, "move_to", ok=False, reason="full",
             summary="destination='Café_bar.Counter'"),
        _rec("Mia Thompson", 1, "fallback", reason="max_steps_exhausted"),
    ]

    replanning = metrics.summarise(records)["replanning"]

    assert replanning["replanned"] == 2
    assert replanning["repeated"] == 1
    assert replanning["gave_up"] == 1
    # 分母只算"还有机会再想一步"的：2 / (2 + 1)
    assert replanning["rate"] == 0.6667


def test_replan_rate_is_none_when_nothing_was_ever_refused():
    records = [_rec("Ron Parker", 0, "move_to")]

    assert metrics.summarise(records)["replanning"]["rate"] is None


# --- 白跑的轮次 --------------------------------------------------------------

def test_a_turn_that_ends_in_fallback_is_wasted():
    records = [
        _rec("Ron Parker", 0, "recall"),
        _rec("Ron Parker", 1, "fallback", reason="max_steps_exhausted"),
        _rec("Emma Harris", 0, "fallback", reason="llm_unavailable"),
        _rec("Mia Thompson", 0, "move_to"),
    ]

    summary = metrics.summarise(records)

    assert summary["turns"] == 3
    assert summary["wasted_turns"]["count"] == 2
    assert summary["wasted_turns"]["by_reason"] == {
        "max_steps_exhausted": 1, "llm_unavailable": 1,
    }
    assert summary["convergence"]["fallback"] == 2
    assert summary["convergence"]["move_to"] == 1
    # 兜底不是工具调用，不该混进调用总数里
    assert summary["calls"] == 2


# --- 有没有真的和别人打交道 --------------------------------------------------

def test_only_successful_world_changes_count():
    records = [
        _rec("Ron Parker", 0, "send_mail", ok=False, reason="unknown_recipient"),
        _rec("Ron Parker", 1, "stay"),
        _rec("Emma Harris", 0, "give_item"),
        _rec("Emma Harris", 1, "move_to"),
    ]

    change = metrics.summarise(records)["world_change"]

    assert change["turns"] == 1                     # 发信失败的那轮不算
    assert change["by_tool"] == {"give_item": 1}
    assert change["rate"] == 0.5


def test_walking_about_does_not_count_as_changing_the_world():
    # 三轮全是走来走去——这正是真跑里 97% 轮次的样子，指标要如实反映。
    records = [
        _rec("Ron Parker", 0, "move_to"),
        _rec("Emma Harris", 0, "stay"),
        _rec("Mia Thompson", 0, "sleep"),
    ]

    assert metrics.summarise(records)["world_change"]["turns"] == 0


def test_tools_nobody_chose_are_listed():
    records = [_rec("Ron Parker", 0, "move_to")]

    never_used = metrics.summarise(records)["never_used"]

    assert "restock" in never_used
    assert "move_to" not in never_used


# --- 读文件 ------------------------------------------------------------------

def test_load_skips_broken_lines(tmp_path):
    # 日志是多线程追加写的，末尾被截断是常事。少算一行可以，
    # 整份报告出不来不行。
    path = tmp_path / "action.jsonl"
    path.write_text(
        json.dumps(_rec("Ron Parker", 0, "move_to"), ensure_ascii=False) + "\n"
        + "{ this is not json\n"
        + "\n"
        + json.dumps(_rec("Ron Parker", 1, "stay"), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    assert len(metrics.load(path)) == 2


def test_an_empty_log_produces_a_report_not_a_crash():
    summary = metrics.summarise([])

    assert summary["turns"] == 0
    assert summary["steps_per_turn"]["mean"] == 0.0
    assert metrics.format_report(summary)          # 排得出表，不抛异常


# --- 对账：指标模块和真代码有没有走散 -----------------------------------------

def test_the_tool_buckets_match_the_real_registry():
    """指标模块自己抄了一份工具分类，好处是能独立跑，代价是可能走散。

    这个测试就是那道保险：注册表里加一件工具却忘了归类，这里立刻红。
    分类依据用的是 ToolSpec 自己的两个标记，不是人手判断。
    """
    from tools import TOOL_REGISTRY

    buckets = metrics.TIME_SPENDING | metrics.LOOKUP | metrics.WORLD_CHANGING
    assert set(TOOL_REGISTRY) == buckets

    # ⚠️ ``check_inbox`` 是唯一一件"意图是查、却有副作用"的工具：它把信
    # 标成已读。``read_only`` 说的是**副作用**，``LOOKUP`` 说的是**意图**
    # ——这一件上两者分开了。把它算进 WORLD_CHANGING 会让"真正改变世界的
    # 轮次"这个指标被读信灌水。例外只此一件，写死在这里，好让第二件出现
    # 时这条测试立刻变红。
    lookup_with_a_side_effect = {"check_inbox"}
    assert lookup_with_a_side_effect <= metrics.LOOKUP

    for name, spec in TOOL_REGISTRY.items():
        if spec.ends_turn:
            assert name in metrics.TIME_SPENDING, f"{name} 占游戏时间，该归 TIME_SPENDING"
        elif spec.read_only or name in lookup_with_a_side_effect:
            assert name in metrics.LOOKUP, f"{name} 意图是查，该归 LOOKUP"
        else:
            assert name in metrics.WORLD_CHANGING, f"{name} 改变世界，该归 WORLD_CHANGING"


def test_every_rejection_reason_in_the_code_is_classified():
    """扫一遍源码里所有 reject(...) 的理由，断言每一个都已归类。

    新加一条拒绝理由却忘了决定它属于"模型的错"还是"世界说不行"——
    这个测试会告诉你。否则它会悄悄落进未归类桶，而没人会去看报告底部。
    """
    backend = Path(__file__).resolve().parent.parent

    found = set()
    for path in (backend / "tools").glob("*.py"):
        found |= set(re.findall(r'reject\(\s*"([a-z_]+)"', path.read_text(encoding="utf-8")))
    # 循环自己产生的那几个理由不走 reject()，单独扫。扫整个包而不是单个
    # 文件——将来 runtime/ 长出 scheduler.py、budgets.py，它们的拒绝理由
    # 也得跟着被归类。
    for path in (backend / "runtime").glob("*.py"):
        found |= set(re.findall(r'reason="([a-z_]+)"', path.read_text(encoding="utf-8")))

    assert found, "一条拒绝理由都没扫到，正则大概是坏了"
    assert not found - metrics.KNOWN_REASONS, \
        f"这些拒绝理由还没归类：{sorted(found - metrics.KNOWN_REASONS)}"


# --- 成本：读的是另一份日志 ---------------------------------------------------

def _call(operation="decision", latency_ms=800, prompt=1000, completion=60,
          status="success", attempts=1):
    """造一条 LLM 调用记录，字段和 log_llm_call 写出来的一致。"""
    return {
        "ts": "2026-08-26T10:00:00.000",
        "trace_id": "abc123",
        "operation": operation,
        "agent_name": "Ron Parker",
        "call_kind": "tool",
        "model": "deepseek-v4-flash",
        "status": status,
        "attempts": attempts,
        "latency_ms": latency_ms,
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
    }


def test_cost_adds_up_tokens_and_counts_retries():
    calls = [
        _call(prompt=1000, completion=100),
        _call(prompt=2000, completion=200, attempts=3),   # 重试了两次
    ]

    cost = metrics.summarise_cost(calls)

    assert cost["calls"] == 2
    assert cost["tokens"] == {
        "prompt": 3000, "completion": 300, "total": 3300, "per_call": 1650.0,
    }
    # attempts=1 是一次就成，只有超出的部分才是多打出去的请求
    assert cost["retries"] == 2


def test_cost_separates_the_kinds_of_call_and_flags_failures():
    calls = [
        _call(operation="decision"),
        _call(operation="decision"),
        _call(operation="reflection"),
        _call(operation="decision", status="failed"),
    ]

    cost = metrics.summarise_cost(calls)

    assert cost["by_operation"] == {"decision": 3, "reflection": 1}
    assert cost["by_status"]["failed"] == 1
    assert "非成功的调用 1" in metrics.format_cost_report(cost)


def test_latency_percentiles_come_out_in_order():
    calls = [_call(latency_ms=ms) for ms in (100, 200, 300, 400, 5000)]

    latency = metrics.summarise_cost(calls)["latency_ms"]

    assert latency["median"] == 300
    assert latency["p90"] == 5000
    assert latency["max"] == 5000


def test_the_two_summaries_ignore_each_others_records():
    """两份日志字段结构不同。混在一起喂进来，各挑各的，谁都不该被带偏。"""
    mixed = [_rec("Ron Parker", 0, "move_to"), _call()]

    assert metrics.summarise(mixed)["turns"] == 1
    assert metrics.summarise(mixed)["calls"] == 1        # 一次工具调用
    assert metrics.summarise_cost(mixed)["calls"] == 1   # 一次 LLM 请求


def test_a_log_with_no_llm_calls_says_so_instead_of_dividing_by_zero():
    cost = metrics.summarise_cost([_rec("Ron Parker", 0, "move_to")])

    assert cost == {"calls": 0}
    assert "没有 LLM 调用记录" in metrics.format_cost_report(cost)


def test_load_no_longer_throws_away_llm_records(tmp_path):
    path = tmp_path / "llm.jsonl"
    path.write_text(json.dumps(_call(), ensure_ascii=False) + "\n", encoding="utf-8")

    assert len(metrics.load(path)) == 1


def test_loading_a_file_that_is_not_there_gives_nothing_not_an_error(tmp_path):
    assert metrics.load(tmp_path / "never-written.jsonl") == []


# ---------- 本可避免的驳回：量的是 agent，不是世界 ----------

def test_foreseeable_reasons_are_a_subset_of_environment_ones():
    """这一刀是**正交**的：它切的是 ENVIRONMENT 那一类的内部。
    漏到别处去（比如把 already_known 算进来）就变成两套分类打架。"""
    assert metrics.FORESEEABLE_REASONS <= metrics.ENVIRONMENT_REASONS


def test_it_counts_the_refusals_the_agent_could_have_predicted():
    """店几点关门是常识，别人此刻在哪不是。"""
    records = [
        _rec("Emma Harris", 0, "move_to", ok=False, reason="closed"),
        _rec("Emma Harris", 1, "give_item", ok=False, reason="target_absent"),
        _rec("Emma Harris", 2, "stay"),
    ]

    refused = metrics.summarise(records)["environment_refusals"]

    assert refused["count"] == 2
    assert refused["foreseeable"] == 1
    assert refused["foreseeable_rate"] == 0.5


def test_no_refusals_means_no_ratio_not_a_zero():
    """一次都没被拒的时候，"本可避免率 0%" 会被读成"表现完美"。
    没有分母就该是 None。"""
    records = [_rec("Emma Harris", 0, "stay")]

    assert metrics.summarise(records)["environment_refusals"]["foreseeable_rate"] is None


def test_the_report_marks_which_ones_it_should_have_known():
    records = [
        _rec("Emma Harris", 0, "buy", ok=False, reason="insufficient_funds"),
        _rec("Emma Harris", 1, "stay"),
    ]

    text = metrics.format_report(metrics.summarise(records))

    assert "它本来就该知道" in text
    assert "本可避免" in text
