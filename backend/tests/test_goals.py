"""任务系统的单元测试。

最要紧的一条：**完成判定只认世界状态，不认模型的说法**。没有客观判定，
就说不出"任务成功率 70%"——因为根本没有"算不算做完"的定义。
不涉及任何 LLM 调用。"""

import pytest

from agents.agent import EmmaHarris
from economy import Economy
from goals import DELIVER, MAX_ACTIVE, GoalStore
from memory.memory_system import MemorySystem
from tools import get_tool
from world import World


@pytest.fixture
def store(tmp_path):
    return GoalStore(path=tmp_path / "goals.json")


@pytest.fixture
def wallet(tmp_path, monkeypatch):
    economy = Economy(path=tmp_path / "economy.json")
    monkeypatch.setattr("economy.economy", economy)
    return economy


def _agent(tmp_path, location="Emma_home.Living_room"):
    memory = MemorySystem(retention_days=15, memory_dir=tmp_path / "mem")
    memory.initialize_agents(["Emma Harris"])
    return EmmaHarris(memory, location)


def _world(minutes=10 * 60, day=1, holdings=None, locations=None):
    return World(time_minutes=minutes, life_day=day,
                 agent_locations=locations or {}, holdings=holdings or {})


# ---------- 判定只看世界状态 ----------

def test_delivery_is_met_only_when_the_person_actually_holds_it(store):
    store.accept("Emma Harris", DELIVER, "Adam Harris", "cold_medicine",
                 deadline_minute=18 * 60, life_day=1, reason="Adam is ill")

    empty = _world()
    assert store.active_for("Emma Harris", 1)[0].is_met(empty) is False

    # Emma 自己买到了，但还没交给 Adam —— 仍然不算完成。
    in_emmas_bag = _world(holdings={"Emma Harris": {"cold_medicine": 1}})
    assert store.active_for("Emma Harris", 1)[0].is_met(in_emmas_bag) is False

    # 送到 Adam 手上才算数。
    delivered = _world(holdings={"Adam Harris": {"cold_medicine": 1}})
    assert store.active_for("Emma Harris", 1)[0].is_met(delivered) is True


def test_settling_marks_it_done_and_clears_it_from_view(store):
    store.accept("Emma Harris", DELIVER, "Adam Harris", "cold_medicine",
                 deadline_minute=18 * 60, life_day=1)
    world = _world(holdings={"Adam Harris": {"cold_medicine": 1}})

    changed = store.settle("Emma Harris", world)

    assert [g.status for g in changed] == ["done"]
    assert store.active_for("Emma Harris", 1) == []
    assert store.summary_for("Emma Harris", world) == ""     # 不再挡在眼前


def test_deadline_passing_marks_it_failed(store):
    store.accept("Emma Harris", DELIVER, "Adam Harris", "cold_medicine",
                 deadline_minute=12 * 60, life_day=1)

    changed = store.settle("Emma Harris", _world(minutes=13 * 60))

    assert [g.status for g in changed] == ["failed"]
    assert store.stats()["failed"] == 1


def test_a_task_does_not_survive_into_the_next_day(store):
    # 期限是"当天几点"，跨天即作废——两天的模拟里跨天目标本就没机会完成。
    store.accept("Emma Harris", DELIVER, "Adam Harris", "cold_medicine",
                 deadline_minute=18 * 60, life_day=1)

    changed = store.settle("Emma Harris", _world(minutes=9 * 60, day=2))

    assert [g.status for g in changed] == ["failed"]


# ---------- 上下文：免费、随时可见、带状态 ----------

def test_summary_states_whether_it_is_done_yet(store):
    store.accept("Emma Harris", DELIVER, "Adam Harris", "cold_medicine",
                 deadline_minute=18 * 60, life_day=1, reason="Adam is ill")

    pending = store.summary_for("Emma Harris", _world(minutes=10 * 60))
    assert "cold_medicine" in pending
    assert "Adam Harris" in pending
    assert "not done yet" in pending
    assert "Adam is ill" in pending                          # 当初为什么接下这事

    met = store.summary_for(
        "Emma Harris", _world(minutes=10 * 60, holdings={"Adam Harris": {"cold_medicine": 1}}))
    assert "already satisfied" in met


def test_summary_warns_when_time_is_running_out(store):
    store.accept("Emma Harris", DELIVER, "Adam Harris", "cold_medicine",
                 deadline_minute=12 * 60, life_day=1)

    calm = store.summary_for("Emma Harris", _world(minutes=6 * 60))
    urgent = store.summary_for("Emma Harris", _world(minutes=11 * 60 + 30))

    assert "minutes left" not in calm                        # 还早，不必催
    assert "30 minutes left" in urgent


def test_no_tasks_means_no_clutter(store):
    assert store.summary_for("Emma Harris", _world()) == ""


# ---------- 上限：扛太多等于一件都做不成 ----------

def test_cannot_take_on_more_than_the_cap(store):
    assert MAX_ACTIVE == 2
    for item in ["bread", "milk", "eggs"]:
        result = store.accept("Emma Harris", DELIVER, "Adam Harris", item,
                              deadline_minute=18 * 60, life_day=1)
    assert result["ok"] is False
    assert result["reason"] == "too_many"
    assert len(result["current"]) == 2                       # 告诉它手头有什么


def test_taking_the_same_task_twice_is_refused(store):
    store.accept("Emma Harris", DELIVER, "Adam Harris", "milk",
                 deadline_minute=18 * 60, life_day=1)
    again = store.accept("Emma Harris", DELIVER, "Adam Harris", "milk",
                         deadline_minute=20 * 60, life_day=1)

    assert again["ok"] is False
    assert again["reason"] == "already_taken"


def test_finishing_one_frees_a_slot(store):
    store.accept("Emma Harris", DELIVER, "Adam Harris", "bread",
                 deadline_minute=18 * 60, life_day=1)
    store.accept("Emma Harris", DELIVER, "Adam Harris", "milk",
                 deadline_minute=18 * 60, life_day=1)
    store.settle("Emma Harris", _world(holdings={"Adam Harris": {"bread": 1}}))

    assert store.accept("Emma Harris", DELIVER, "Adam Harris", "eggs",
                        deadline_minute=18 * 60, life_day=1)["ok"] is True


def test_goals_survive_a_restart(tmp_path):
    path = tmp_path / "goals.json"
    GoalStore(path=path).accept("Emma Harris", DELIVER, "Adam Harris", "milk",
                                deadline_minute=18 * 60, life_day=1)

    reopened = GoalStore(path=path)
    assert len(reopened.active_for("Emma Harris", 1)) == 1


# ---------- accept_task 工具 ----------

def _accept(agent, world, monkeypatch, store, **kwargs):
    monkeypatch.setattr("goals.goal_store", store)
    args = {"thought": "I should remember this", "item": "cold_medicine",
            "for_person": "Adam Harris", "by_hour": 18, "reason": "Adam is ill"}
    args.update(kwargs)
    return get_tool("accept_task").handler(agent, args, world)


def test_tool_records_the_task(tmp_path, monkeypatch, store, wallet):
    result = _accept(_agent(tmp_path), _world(), monkeypatch, store)

    assert result["ok"] is True
    assert "cold_medicine" in result["observation"]
    assert len(store.active_for("Emma Harris", 1)) == 1


def test_tool_rejects_something_no_shop_sells(tmp_path, monkeypatch, store, wallet):
    # 判不出完成与否的目标对评估毫无价值，只会把上下文塞满。
    result = _accept(_agent(tmp_path), _world(), monkeypatch, store, item="a nice afternoon")

    assert result["ok"] is False
    assert result["reason"] == "unknown_item"


def test_tool_rejects_a_deadline_already_gone(tmp_path, monkeypatch, store, wallet):
    result = _accept(_agent(tmp_path), _world(minutes=20 * 60), monkeypatch, store, by_hour=9)

    assert result["ok"] is False
    assert result["reason"] == "deadline_passed"


def test_tool_tells_you_what_you_are_already_carrying(tmp_path, monkeypatch, store, wallet):
    _accept(_agent(tmp_path), _world(), monkeypatch, store, item="bread")
    _accept(_agent(tmp_path), _world(), monkeypatch, store, item="milk")

    third = _accept(_agent(tmp_path), _world(), monkeypatch, store, item="eggs")

    assert third["ok"] is False
    assert "bread" in third["observation"] or "milk" in third["observation"]


def test_accept_task_costs_no_game_time():
    assert get_tool("accept_task").terminal is False


# ---------- give_item：任务的终点 ----------

def test_giving_completes_a_delivery_task(tmp_path, monkeypatch, store, wallet):
    # 整条链的最后一步：买到手 -> 当面交出去 -> 任务达成。
    monkeypatch.setattr("goals.goal_store", store)
    emma = _agent(tmp_path, "Pharmacy.Medicine_shelf")
    wallet._balances["Emma Harris"] = 50
    wallet.buy("Emma Harris", "cold_medicine")

    world_before = _world(holdings=wallet.all_holdings())
    store.accept("Emma Harris", DELIVER, "Adam Harris", "cold_medicine",
                 deadline_minute=18 * 60, life_day=1)
    assert "not done yet" in store.summary_for("Emma Harris", world_before)

    together = World(time_minutes=10 * 60, life_day=1,
                     agent_locations={"Emma Harris": "Park.Bench",
                                      "Adam Harris": "Park.Tree"})
    result = get_tool("give_item").handler(
        emma, {"thought": "here you go", "to": "Adam Harris", "item": "cold_medicine"},
        together)

    assert result["ok"] is True
    assert wallet.holdings("Adam Harris") == {"cold_medicine": 1}
    assert wallet.holdings("Emma Harris") == {}

    settled = store.settle("Emma Harris", _world(holdings=wallet.all_holdings()))
    assert [g.status for g in settled] == ["done"]


def test_you_cannot_hand_things_over_from_a_distance(tmp_path, monkeypatch, wallet):
    # 和 transfer 相反：钱能隔空转，东西得当面递。
    emma = _agent(tmp_path)
    wallet._holdings["Emma Harris"] = {"milk": 1}
    apart = World(time_minutes=10 * 60,
                  agent_locations={"Emma Harris": "Emma_home.Kitchen",
                                   "Adam Harris": "Park.Bench"})

    result = get_tool("give_item").handler(
        emma, {"thought": "catch", "to": "Adam Harris", "item": "milk"}, apart)

    assert result["ok"] is False
    assert result["reason"] == "target_absent"
    assert "Park" not in result["observation"]           # 依旧不泄露对方去向
    assert wallet.holdings("Emma Harris") == {"milk": 1}  # 东西还在自己手上


def test_you_cannot_give_what_you_do_not_have(tmp_path, monkeypatch, wallet):
    emma = _agent(tmp_path, "Park.Bench")
    together = World(time_minutes=10 * 60,
                     agent_locations={"Emma Harris": "Park.Bench",
                                      "Adam Harris": "Park.Tree"})

    result = get_tool("give_item").handler(
        emma, {"thought": "here", "to": "Adam Harris", "item": "milk"}, together)

    assert result["ok"] is False
    assert result["reason"] == "not_carrying"


def test_money_still_moves_without_meeting(tmp_path, monkeypatch, wallet):
    # 对照组：转账不需要见面，这个不对称是刻意的。
    emma = _agent(tmp_path)
    apart = World(time_minutes=10 * 60,
                  agent_locations={"Emma Harris": "Emma_home.Kitchen",
                                   "Adam Harris": "Park.Bench"})

    result = get_tool("transfer").handler(
        emma, {"thought": "pocket money", "to": "Adam Harris", "amount": 5}, apart)

    assert result["ok"] is True
