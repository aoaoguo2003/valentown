"""事件：世界里发生过什么，以及**谁察觉得到**。

上下文一直只说"当前状态"。转账对收款人是完全无声的——Emma 借到的 5 块钱
到账时她那边一个字都没有，只有余额从 3 变成 8，得她自己发现。这套东西补的
就是那一半。

⚠️ 这个文件的重点不是"事件记下来了没有"，是**信息不对称有没有被拆掉**。
小镇里居民只看得见同区域的人，别人的钱、店里的货、信的内容都得花动作去取。
事件系统一旦做成全局广播，这层设计一次就没了，通信也随之失去存在的理由。
所以下面一半的测试在验**看不见什么**。
"""

import pytest
import world.events as events
from runtime.scheduler import Town
from world.events import EventLog


@pytest.fixture
def log():
    fresh = EventLog()
    fresh.set_clock(1, 10 * 60)
    return fresh


# --- 谁察觉得到 ----------------------------------------------------------------

def test_the_one_who_did_it_is_never_told_about_it(log):
    """他自己做的事，不必再告诉他一遍。"""
    log.record(events.MONEY_SENT, "Gavin Harris",
               visible_to={"Emma Harris", "Gavin Harris"}, amount=5)

    assert log.take_new("Gavin Harris") == []
    assert len(log.take_new("Emma Harris")) == 1


def test_money_arriving_is_something_the_recipient_notices(log):
    log.record(events.MONEY_SENT, "Gavin Harris",
               visible_to={"Emma Harris"}, amount=5, recipient="Emma Harris")

    seen = log.take_new("Emma Harris")

    assert [e.describe_to("Emma Harris") for e in seen] == ["Gavin Harris sent you 5."]
    assert log.take_new("Mia Thompson") == [], "路人不该知道别人之间转了钱"


def test_what_other_people_buy_is_invisible_to_everyone(log):
    """**这条最要紧。**别人买了什么你看不见——否则等于免费给了一份
    全镇消费清单，`check_stock` 和写信打听就都没有意义了。"""
    log.record(events.ITEM_BOUGHT, "Gavin Harris", item="coffee", area="Café_bar")

    for watcher in ("Emma Harris", "Mia Thompson", "Ron Parker"):
        assert log.take_new(watcher) == []
    # 但它仍然进日志——排查和判据要用
    assert log.happened(events.ITEM_BOUGHT, item="coffee")


def test_mail_does_not_repeat_what_the_context_already_says(log):
    """未读**数量**上下文里本来就有，事件再播一遍只是费 token。"""
    log.record(events.MAIL_SENT, "Gavin Harris",
               recipient="Emma Harris", subject="hello")

    assert log.take_new("Emma Harris") == []
    assert log.happened(events.MAIL_SENT, recipient="Emma Harris")


# --- 已读水位 ------------------------------------------------------------------

def test_you_only_hear_about_something_once(log):
    log.record(events.MONEY_SENT, "Gavin Harris", visible_to={"Emma Harris"}, amount=5)

    assert len(log.take_new("Emma Harris")) == 1
    assert log.take_new("Emma Harris") == []


def test_each_person_has_their_own_high_water_mark(log):
    log.record(events.MONEY_SENT, "Gavin Harris",
               visible_to={"Emma Harris", "Mia Thompson"}, amount=5)
    log.take_new("Emma Harris")

    assert len(log.take_new("Mia Thompson")) == 1, "一个人读过不该让另一个人漏掉"


# --- 发事件的地方：世界服务，不是工具 ---------------------------------------------

def test_a_transfer_tells_the_recipient_and_nobody_else():
    with Town(days=1) as town:
        town.economy.seed(balances={"Gavin Harris": 20, "Emma Harris": 3})
        town.economy.transfer("Gavin Harris", "Emma Harris", 5)

        assert [e.describe_to("Emma Harris")
                for e in events.event_log.take_new("Emma Harris")] == \
            ["Gavin Harris sent you 5."]
        assert events.event_log.take_new("Mia Thompson") == []


def test_handing_something_over_tells_the_person_who_received_it():
    with Town(days=1) as town:
        town.economy.seed(holdings={"Emma Harris": {"cold_medicine": 1}})
        town.economy.give("Emma Harris", "Adam Harris", "cold_medicine")

        seen = events.event_log.take_new("Adam Harris")

        assert [e.describe_to("Adam Harris") for e in seen] == \
            ["Emma Harris handed you cold_medicine."]


def test_seeding_a_scenario_emits_nothing_because_it_bypasses_the_services():
    """``seed`` 绕过 buy / give / transfer 直接摆世界。事件由**世界服务**发，
    所以埋场景不会伪造出一串"刚刚发生"——否则每道题一开局就先播一遍剧透。"""
    with Town(days=1) as town:
        town.economy.seed(balances={"Emma Harris": 3},
                          holdings={"Arthur Morgan": {"cake": 1}})

        assert events.event_log.all() == []


# --- 隔离 ----------------------------------------------------------------------

def test_two_towns_do_not_share_an_event_log():
    """评估会在同一个进程里连跑几十座小镇。漏还原一处，第二座就带着
    第一座的事件开局。"""
    with Town(days=1) as first:
        first.economy.seed(balances={"Gavin Harris": 20})
        first.economy.transfer("Gavin Harris", "Emma Harris", 5)
        assert events.event_log.all()

    with Town(days=1):
        assert events.event_log.all() == []


# --- 判据：事件比轮询状态准 -------------------------------------------------------

def test_an_event_stays_true_even_after_the_state_moves_on():
    """**这就是判据该看事件的理由。**药在 Emma 手上，交出去就没了；
    状态只能靠每批决策守着看，事件是就是。"""
    with Town(days=1) as town:
        town.economy.seed(holdings={"Emma Harris": {"cold_medicine": 1}})
        town.economy.give("Emma Harris", "Adam Harris", "cold_medicine")
        town.economy.give("Adam Harris", "Mia Thompson", "cold_medicine")

        # 药已经不在 Emma 也不在 Adam 手上了
        assert town.economy.holdings("Adam Harris").get("cold_medicine", 0) == 0
        # 但"Emma 交给过 Adam"这件事永远成立
        assert events.event_log.happened(
            events.ITEM_GIVEN, item="cold_medicine", receiver="Adam Harris")


# --- 一轮只能取一次 --------------------------------------------------------------

def test_the_whole_turn_sees_the_same_events_not_just_the_first_step(tmp_path):
    """``take_new`` 有副作用（推进已读水位），而决策循环**每一步**都会重新
    组装上下文。每步取一遍的话，第一步就把事件吃光了，后面几步全看不见——
    而且不会报错，只会让模型在第二步之后忘掉刚发生的事。

    所以循环在**进入循环之前**取一次，整轮共用同一份。
    """
    from unittest.mock import patch

    from agents.agent import EmmaHarris
    from memory.memory_system import MemorySystem
    from runtime.agent_runtime import run_decision_loop
    from world.snapshot import World

    with Town(days=1) as town:
        town.economy.seed(balances={"Gavin Harris": 20})
        town.economy.transfer("Gavin Harris", "Emma Harris", 5)

        memory = MemorySystem(retention_days=15, memory_dir=tmp_path)
        memory.initialize_agents(["Emma Harris"])
        emma = EmmaHarris(memory, "Park.Bench")

        seen = []
        calls = [
            {"name": "recall", "args": {"thought": "t", "query": "money"}},
            {"name": "stay", "args": {"thought": "t", "action": "wait",
                                      "duration_minutes": 60, "talk_to": "nobody"}},
        ]

        def fake(agent_name, context, schemas):
            seen.append("Gavin Harris sent you 5." in context)
            return calls.pop(0)

        with patch.object(emma.llm, "call_tools", fake):
            run_decision_loop(
                emma, internal_state={"values": {}}, triggers=[], day_number=1,
                time_text="10:00 AM", current_location="Park.Bench",
                last_action=None,
                with_world=lambda fn: fn(World(time_minutes=600,
                                               agent_locations={"Emma Harris": "Park.Bench"})),
            )

    assert seen == [True, True], f"第二步就看不见了：{seen}"
