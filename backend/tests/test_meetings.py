"""承诺机制的单元测试。

两条最要紧的：**履约要求双方都在场**（只查自己的话，一个人在空荡荡的公园
干等也算成功，指标就废了），以及**绝不留下单边的约定**（一个人以为约好了、
另一个人根本不知道，比没约还糟）。不涉及任何 LLM 调用。"""

import pytest

from agents.agent import EmmaHarris
from world.goals import MAX_ACTIVE, MEET, GoalStore
from memory.memory_system import MemorySystem
from tools import get_tool
from world.locations import MEETING_AREAS
from world.snapshot import World

EMMA = "Emma Harris"
ADAM = "Adam Harris"
GAVIN = "Gavin Harris"


@pytest.fixture
def store(tmp_path, monkeypatch):
    goals = GoalStore(path=tmp_path / "goals.json")
    monkeypatch.setattr("world.goals.goal_store", goals)
    return goals


def _agent(tmp_path, location="Emma_home.Living_room"):
    memory = MemorySystem(retention_days=15, memory_dir=tmp_path / "mem")
    memory.initialize_agents([EMMA])
    return EmmaHarris(memory, location)


def _world(minutes=10 * 60, day=1, **locations):
    return World(time_minutes=minutes, life_day=day, agent_locations=locations)


# ---------- 双方都在才算履约 ----------

def test_one_person_waiting_alone_is_not_a_kept_promise(store):
    store.arrange_meeting(EMMA, ADAM, "Park", at_minute=16 * 60, life_day=1)
    goal = store.active_for(EMMA, 1)[0]

    # Emma 准时到了，Adam 没来 —— 这不是履约，是干等。
    alone = _world(minutes=16 * 60, **{EMMA: "Park.Bench", ADAM: "Adam_home.Kitchen"})
    assert goal.is_met(alone) is False

    together = _world(minutes=16 * 60, **{EMMA: "Park.Bench", ADAM: "Park.Tree"})
    assert goal.is_met(together) is True      # 同区域即可，不必同一张长椅


def test_neither_showing_up_is_not_a_kept_promise(store):
    store.arrange_meeting(EMMA, ADAM, "Park", at_minute=16 * 60, life_day=1)
    goal = store.active_for(EMMA, 1)[0]
    elsewhere = _world(minutes=16 * 60,
                       **{EMMA: "Café_bar.Counter", ADAM: "Café_bar.Patio"})
    assert goal.is_met(elsewhere) is False    # 两人是碰上了，但不在约好的地方


def test_missing_the_hour_breaks_it_for_both(store):
    store.arrange_meeting(EMMA, ADAM, "Park", at_minute=16 * 60, life_day=1)

    late = _world(minutes=17 * 60, **{EMMA: "Emma_home.Kitchen", ADAM: "Park.Bench"})
    assert [g.status for g in store.settle(EMMA, late)] == ["failed"]
    assert [g.status for g in store.settle(ADAM, late)] == ["failed"]

    assert store.meeting_record()["broken"] == 2


def test_keeping_it_settles_both_sides(store):
    store.arrange_meeting(EMMA, ADAM, "Park", at_minute=16 * 60, life_day=1)
    met = _world(minutes=15 * 60 + 40, **{EMMA: "Park.Bench", ADAM: "Park.Tree"})

    assert [g.status for g in store.settle(EMMA, met)] == ["done"]
    assert [g.status for g in store.settle(ADAM, met)] == ["done"]

    record = store.meeting_record()
    assert record == {"arranged": 1, "honored": 1, "broken": 0, "rate": 1.0}


# ---------- 绝不留下单边的约定 ----------

def test_both_sides_get_a_record(store):
    store.arrange_meeting(EMMA, ADAM, "Café_bar", at_minute=16 * 60, life_day=1)

    emma = store.active_for(EMMA, 1)
    adam = store.active_for(ADAM, 1)
    assert len(emma) == 1 and len(adam) == 1
    assert emma[0].person == ADAM and adam[0].person == EMMA
    assert emma[0].what == adam[0].what == "Café_bar"
    assert emma[0].deadline_minute == adam[0].deadline_minute


def test_a_full_diary_on_one_side_cancels_the_whole_thing(store):
    # Adam 的约会名额已满：Emma 这边也不能留下记录，
    # 否则她会以为约好了，而他根本不知道。
    # 两个**不同**的约会才占满名额——同一个人同一地点约两次会被当成
    # 重复（改期不是新约定），所以这里换人换地方。
    store.accept(ADAM, MEET, GAVIN, "Park", 10 * 60, life_day=1)
    store.accept(ADAM, MEET, "Mia Thompson", "Café_bar", 11 * 60, life_day=1)
    assert len(store.active_for(ADAM, 1)) == MAX_ACTIVE

    result = store.arrange_meeting(EMMA, ADAM, "Café_bar", at_minute=16 * 60, life_day=1)

    assert result["ok"] is False
    assert result["reason"] == "too_many"
    assert store.active_for(EMMA, 1) == []          # 单边记录必须被清干净


def test_errands_and_meetings_are_counted_separately(store):
    # 手上有跑腿的差事，不该妨碍你答应见个面。
    from world.goals import DELIVER

    for item in ("bread", "milk"):
        store.accept(EMMA, DELIVER, ADAM, item, 18 * 60, life_day=1)

    assert store.arrange_meeting(EMMA, ADAM, "Park", 16 * 60, life_day=1)["ok"] is True


# ---------- 临近时的强制提醒 ----------

def test_an_approaching_meeting_is_pushed_to_the_top(store):
    store.arrange_meeting(EMMA, ADAM, "Park", at_minute=16 * 60, life_day=1)

    early = store.summary_for(EMMA, _world(minutes=12 * 60))
    close = store.summary_for(EMMA, _world(minutes=15 * 60 + 20))

    assert "You are due at" not in early             # 还早，不必催
    assert close.startswith("You are due at Park at 4:00 PM to meet Adam Harris")
    assert "3:20 PM" in close                        # 而且告诉它现在几点


def test_no_reminder_once_you_are_both_there(store):
    store.arrange_meeting(EMMA, ADAM, "Park", at_minute=16 * 60, life_day=1)
    arrived = _world(minutes=15 * 60 + 30, **{EMMA: "Park.Bench", ADAM: "Park.Tree"})

    summary = store.summary_for(EMMA, arrived)

    assert "You are due at" not in summary           # 已经碰上了，别再催
    assert "already satisfied" in summary


def test_meeting_reads_naturally_in_the_plan(store):
    store.arrange_meeting(EMMA, ADAM, "Park", at_minute=16 * 60, life_day=1,
                          reason="to hand over the medicine")
    summary = store.summary_for(EMMA, _world(minutes=12 * 60))

    assert "meet Adam Harris at Park at 4:00 PM" in summary
    assert "hand over the medicine" in summary


# ---------- accept_meeting 工具 ----------

def _arrange(agent, world, **kwargs):
    args = {"thought": "we should sort this out", "with_person": ADAM,
            "where": "Park", "at_hour": 16, "reason": "to hand over the medicine"}
    args.update(kwargs)
    return get_tool("accept_meeting").handler(agent, args, world)


def test_tool_puts_it_on_both_plans(tmp_path, store):
    result = _arrange(_agent(tmp_path), _world())

    assert result["ok"] is True
    assert "Adam Harris" in result["observation"]
    assert "4:00 PM" in result["observation"]
    assert len(store.active_for(EMMA, 1)) == 1
    assert len(store.active_for(ADAM, 1)) == 1       # 对方无需回信即可生效


def test_tool_refuses_an_hour_already_gone(tmp_path, store):
    result = _arrange(_agent(tmp_path), _world(minutes=20 * 60), at_hour=9)

    assert result["ok"] is False
    assert result["reason"] == "time_passed"
    assert store.active_for(EMMA, 1) == []


def test_tool_refuses_meeting_yourself(tmp_path, store):
    assert _arrange(_agent(tmp_path), _world(), with_person=EMMA)["reason"] == "self_meeting"


def test_meeting_areas_are_places_not_anchors():
    # 见面按区域算——同在咖啡馆就算碰上，不必挤在同一张桌子旁。
    assert "Park" in MEETING_AREAS
    assert "Café_bar" in MEETING_AREAS
    assert "Emma_home" in MEETING_AREAS
    assert "Park.Bench" not in MEETING_AREAS


def test_accept_meeting_costs_no_game_time():
    assert get_tool("accept_meeting").ends_turn is False


# ---------- 整条链：约定让交付不再靠运气 ----------

def test_arranging_turns_a_chance_encounter_into_a_plan(tmp_path, store, monkeypatch):
    """141 次"对方不在场"的解法。

    Emma 手上有药要给 Adam。此前她只能走到某处、期望撞见他；现在她可以
    约定一个时间地点，而这个约定会一直摆在两个人眼前。
    """
    from world.economy import Economy

    wallet = Economy(path=tmp_path / "economy.json")
    monkeypatch.setattr("world.economy.economy", wallet)
    wallet._holdings[EMMA] = {"cold_medicine": 1}

    emma = _agent(tmp_path)
    apart = _world(**{EMMA: "Emma_home.Kitchen", ADAM: "Park.Bench"})

    # 隔空交不了东西，而拒绝理由现在会指出那条路。
    blocked = get_tool("give_item").handler(
        emma, {"thought": "here you go", "to": ADAM, "item": "cold_medicine"}, apart)
    assert blocked["reason"] == "target_absent"
    assert "write" in blocked["observation"]

    assert _arrange(emma, apart)["ok"] is True

    # 到点，两人都到了 Park —— 交付这才成为可能。
    together = _world(minutes=16 * 60, **{EMMA: "Park.Bench", ADAM: "Park.Tree"})
    handed = get_tool("give_item").handler(
        emma, {"thought": "as agreed", "to": ADAM, "item": "cold_medicine"}, together)

    assert handed["ok"] is True
    assert wallet.holdings(ADAM) == {"cold_medicine": 1}
    assert [g.status for g in store.settle(EMMA, together)] == ["done"]


def test_re_arranging_the_same_pairing_is_treated_as_a_duplicate(store):
    """同一个人、同一地点约第二次会被拒——改期不是新约定。

    这条略显僵硬（想改时间只能重来），但比留下两个互相矛盾的约定安全：
    双方各持一份记录，两份对不上的话谁都不知道该几点到。
    """
    assert store.arrange_meeting(EMMA, ADAM, "Park", 16 * 60, life_day=1)["ok"] is True
    again = store.arrange_meeting(EMMA, ADAM, "Park", 18 * 60, life_day=1)

    assert again["ok"] is False
    assert again["reason"] == "already_taken"
    assert len(store.active_for(EMMA, 1)) == 1      # 没有留下第二份互相矛盾的记录


# ---------- 动作不许睡过约定 ----------

def _run_loop(agent, store, calls, monkeypatch, minutes, day=1):
    """驱动一轮真实的决策循环，用脚本化的假 LLM。"""
    import threading

    from runtime import run_decision_loop
    from world.snapshot import World

    queue = list(calls)
    monkeypatch.setattr(
        agent.llm, "call_tools",
        lambda name, context, schemas: queue.pop(0) if queue else None)

    lock = threading.Lock()
    locations = {EMMA: agent.current_location, ADAM: "Adam_home.Living_room"}

    def with_world(fn):
        with lock:
            return fn(World(time_minutes=minutes, life_day=day,
                            agent_locations=locations))

    return run_decision_loop(
        agent,
        internal_state={"values": {"hunger": 30, "energy": 40, "social": 50}},
        triggers=[], day_number=day, time_text="12:00 PM",
        current_location=agent.current_location, last_action=None,
        with_world=with_world,
    )


def _sleep_call(minutes=540):
    return {"name": "sleep", "args": {"thought": "long day", "duration_minutes": minutes}}


def test_a_long_sleep_is_cut_short_by_an_appointment(tmp_path, store, monkeypatch):
    """一个九小时的午觉能把当天所有约定一并作废。

    这不是中断——没有任何东西把她叫醒，只是这个动作一开始就不允许有那么长。
    """
    from world.goals import COMMITMENT_BUFFER_MINUTES

    agent = _agent(tmp_path, "Emma_home.Living_room")
    store.arrange_meeting(EMMA, ADAM, "Park", at_minute=16 * 60, life_day=1)

    decision, steps = _run_loop(agent, store, [_sleep_call(540)], monkeypatch,
                                minutes=12 * 60)

    # 12:00 睡到 15:45 就得起——留 15 分钟走去公园。
    assert decision["duration_minutes"] == (16 * 60 - COMMITMENT_BUFFER_MINUTES) - 12 * 60
    assert decision["duration_minutes"] == 225
    assert "due somewhere" in steps[-1]["observation"]     # 而且说明了为什么变短


def test_nothing_is_clipped_without_a_commitment(tmp_path, store, monkeypatch):
    agent = _agent(tmp_path, "Emma_home.Living_room")

    decision, _ = _run_loop(agent, store, [_sleep_call(540)], monkeypatch,
                            minutes=12 * 60)

    assert decision["duration_minutes"] == 540             # 没约，睡个够


def test_an_action_that_already_fits_is_left_alone(tmp_path, store, monkeypatch):
    agent = _agent(tmp_path, "Emma_home.Living_room")
    store.arrange_meeting(EMMA, ADAM, "Park", at_minute=20 * 60, life_day=1)

    decision, steps = _run_loop(agent, store, [_sleep_call(60)], monkeypatch,
                                minutes=12 * 60)

    assert decision["duration_minutes"] == 60
    assert "due somewhere" not in steps[-1]["observation"]  # 赶得上就别啰嗦


def test_being_almost_late_still_leaves_a_workable_action(tmp_path, store, monkeypatch):
    # 约会只剩五分钟：裁成负数是没意义的，给一个最短动作让它下一轮重新决定。
    from world.locations import MIN_ACTION_MINUTES

    agent = _agent(tmp_path, "Emma_home.Living_room")
    store.arrange_meeting(EMMA, ADAM, "Park", at_minute=12 * 60 + 5, life_day=1)

    decision, _ = _run_loop(agent, store, [_sleep_call(540)], monkeypatch,
                            minutes=12 * 60)

    assert decision["duration_minutes"] == MIN_ACTION_MINUTES


def test_an_errand_deadline_clips_things_too(tmp_path, store, monkeypatch):
    # 约会的时刻和任务的期限是同一回事——都是"不能睡过头"的那个点。
    from world.goals import DELIVER

    agent = _agent(tmp_path, "Emma_home.Living_room")
    store.accept(EMMA, DELIVER, ADAM, "cold_medicine", 14 * 60, life_day=1)

    decision, _ = _run_loop(agent, store, [_sleep_call(540)], monkeypatch,
                            minutes=12 * 60)

    assert decision["duration_minutes"] == 105             # 12:00 -> 13:45


def test_the_earliest_deadline_wins(tmp_path, store, monkeypatch):
    from world.goals import DELIVER

    agent = _agent(tmp_path, "Emma_home.Living_room")
    store.accept(EMMA, DELIVER, ADAM, "cold_medicine", 18 * 60, life_day=1)
    store.arrange_meeting(EMMA, ADAM, "Park", at_minute=14 * 60, life_day=1)

    decision, _ = _run_loop(agent, store, [_sleep_call(540)], monkeypatch,
                            minutes=12 * 60)

    assert decision["duration_minutes"] == 105             # 按 14:00 那个算


def test_ordinary_actions_are_clipped_as_well(tmp_path, store, monkeypatch):
    # 不只是 sleep：三小时的 stay 同样能睡过一个约定。
    agent = _agent(tmp_path, "Park.Bench")
    store.arrange_meeting(EMMA, ADAM, "Café_bar", at_minute=14 * 60, life_day=1)

    stay = {"name": "stay", "args": {"thought": "nice here", "action": "read a book",
                                     "duration_minutes": 180, "talk_to": "nobody"}}
    decision, _ = _run_loop(agent, store, [stay], monkeypatch, minutes=12 * 60)

    assert decision["duration_minutes"] == 105
