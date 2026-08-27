"""任务系统的单元测试。

最要紧的一条：**完成判定只认世界状态，不认模型的说法**。没有客观判定，
就说不出"任务成功率 70%"——因为根本没有"算不算做完"的定义。
不涉及任何 LLM 调用。"""

import pytest

from agents.agent import EmmaHarris
from world.economy import Economy
from world.goals import DELIVER, MAX_ACTIVE, GoalStore
from memory.memory_system import MemorySystem
from tools import get_tool
from world.snapshot import World


@pytest.fixture
def store(tmp_path):
    return GoalStore(path=tmp_path / "goals.json")


@pytest.fixture
def wallet(tmp_path, monkeypatch):
    economy = Economy(path=tmp_path / "economy.json")
    monkeypatch.setattr("world.economy.economy", economy)
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
    monkeypatch.setattr("world.goals.goal_store", store)
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
    assert get_tool("accept_task").ends_turn is False


# ---------- give_item：任务的终点 ----------

def test_giving_completes_a_delivery_task(tmp_path, monkeypatch, store, wallet):
    # 整条链的最后一步：买到手 -> 当面交出去 -> 任务达成。
    monkeypatch.setattr("world.goals.goal_store", store)
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


# ---------- 递交窗口：机会打开的那一刻说出来 ----------
#
# 上下文里本来就有这三条，只是分三段摆着：能看见谁、身上带着什么、欠谁一件
# 东西。两次 rendezvous 真跑证明模型不会自己把它们连起来——人碰上了、蛋糕
# 还在手上、``give_item`` 一次都没调过。所以窗口打开时拼成一句顶到最前。
#
# ⚠️ 下面一半的测试在验**不该出现的时候不出现**，尤其是那条不许泄露远处
# 的人在哪的规则。

def _owes_adam(store):
    store.accept("Emma Harris", DELIVER, "Adam Harris", "cold_medicine",
                 deadline_minute=18 * 60, life_day=1, reason="Adam is ill")


def test_the_handover_window_is_pointed_out_when_it_opens(store):
    _owes_adam(store)

    text = store.summary_for("Emma Harris", _world(
        locations={"Emma Harris": "Park.Bench", "Adam Harris": "Park.Fountain"},
        holdings={"Emma Harris": {"cold_medicine": 1}}))

    assert "Adam Harris is right here with you" in text
    assert "only works face to face" in text
    # 顶到最前，和临近约会同级——转瞬即逝的东西排在清单后面等于没说。
    assert text.index("right here") < text.index("You have taken on:")


def test_the_window_is_about_the_area_not_the_exact_spot(store):
    """长椅和喷泉是同一个公园。见面按**区域**算，不是按锚点。"""
    _owes_adam(store)

    text = store.summary_for("Emma Harris", _world(
        locations={"Emma Harris": "Park.Bench", "Adam Harris": "Park.Fountain"},
        holdings={"Emma Harris": {"cold_medicine": 1}}))

    assert "right here with you" in text


def test_nothing_is_said_when_they_are_somewhere_else(store):
    _owes_adam(store)

    text = store.summary_for("Emma Harris", _world(
        locations={"Emma Harris": "Park.Bench", "Adam Harris": "Pharmacy.Counter"},
        holdings={"Emma Harris": {"cold_medicine": 1}}))

    assert "right here" not in text


def test_the_window_never_leaks_where_a_distant_person_is(store):
    """**这条最要紧。**世界知道所有人在哪，居民不知道。这一行要是漏出
    对方的位置，写信打听就没有存在意义了。"""
    _owes_adam(store)

    text = store.summary_for("Emma Harris", _world(
        locations={"Emma Harris": "Park.Bench", "Adam Harris": "Cafe_bar.Patio"},
        holdings={"Emma Harris": {"cold_medicine": 1}}))

    assert "Cafe_bar" not in text
    assert "Patio" not in text


def test_nothing_is_said_when_your_hands_are_empty(store):
    """人在眼前但东西还没买到——这时候提"可以交给他"是噪音。"""
    _owes_adam(store)

    text = store.summary_for("Emma Harris", _world(
        locations={"Emma Harris": "Park.Bench", "Adam Harris": "Park.Bench"},
        holdings={"Emma Harris": {}}))

    assert "right here" not in text


def test_the_window_closes_once_they_already_have_it(store):
    """已经交到手了就别再催。判定看的是**对方**手上有没有。"""
    _owes_adam(store)

    text = store.summary_for("Emma Harris", _world(
        locations={"Emma Harris": "Park.Bench", "Adam Harris": "Park.Bench"},
        holdings={"Emma Harris": {"cold_medicine": 1},
                  "Adam Harris": {"cold_medicine": 1}}))

    assert "right here" not in text
    assert "already satisfied" in text


def test_a_task_for_yourself_never_opens_a_window(store):
    """给自己跑腿的任务：不存在"交给对方"这件事。"""
    store.accept("Emma Harris", DELIVER, "Emma Harris", "cold_medicine",
                 deadline_minute=18 * 60, life_day=1, reason="for myself")

    text = store.summary_for("Emma Harris", _world(
        locations={"Emma Harris": "Park.Bench"},
        holdings={"Emma Harris": {}}))

    assert "right here" not in text


# ---------- 见面窗口：通向"当面交"的另一条路 ----------
#
# 只接 DELIVER 那条时，rendezvous 上整段是死的——实测那行字在一整次跑里
# 出现 **0 次**。Arthur 开局就拿着蛋糕，信里问的是"约个时间地点"，他直接
# accept_meeting，从没调过 accept_task。**修得对不对，和修的那条路走不走人，
# 是两件事。**

from world.goals import MEET  # noqa: E402


def _agreed_to_meet(store, area="Park"):
    store.accept("Arthur Morgan", MEET, "Mia Thompson", area,
                 deadline_minute=15 * 60, life_day=1, reason="she asked")


def test_meeting_up_also_opens_the_window(store):
    """**这条就是那次白跑换来的。**没有 DELIVER 任务，只有一个约定，
    人碰上了、东西在手上——窗口一样得开。"""
    _agreed_to_meet(store)

    text = store.summary_for("Arthur Morgan", _world(
        minutes=15 * 60,
        locations={"Arthur Morgan": "Park.Bench", "Mia Thompson": "Park.Tree"},
        holdings={"Arthur Morgan": {"cake": 1}}))

    assert "You are with Mia Thompson right now" in text
    assert "only works face to face" in text
    assert text.index("right now") < text.index("You have taken on:")


def test_empty_handed_at_a_meeting_is_not_worth_a_line(store):
    """两手空空时提"交给对方"是纯噪音。"""
    _agreed_to_meet(store)

    text = store.summary_for("Arthur Morgan", _world(
        minutes=15 * 60,
        locations={"Arthur Morgan": "Park.Bench", "Mia Thompson": "Park.Tree"},
        holdings={"Arthur Morgan": {}}))

    assert "right now" not in text


def test_a_meeting_says_nothing_until_they_show_up(store):
    _agreed_to_meet(store)

    text = store.summary_for("Arthur Morgan", _world(
        minutes=15 * 60,
        locations={"Arthur Morgan": "Park.Bench", "Mia Thompson": "Cafe_bar.Patio"},
        holdings={"Arthur Morgan": {"cake": 1}}))

    assert "right now" not in text
    assert "Cafe_bar" not in text, "不许泄露对方在哪"


def test_the_same_person_is_not_named_twice(store):
    """既接了差事又约了见面时，两条窗口说的是同一件事。
    说两遍只会占位置——上下文里每一行都得挣得它的位置。"""
    store.accept("Emma Harris", DELIVER, "Adam Harris", "cold_medicine",
                 deadline_minute=18 * 60, life_day=1, reason="Adam is ill")
    store.accept("Emma Harris", MEET, "Adam Harris", "Park",
                 deadline_minute=15 * 60, life_day=1, reason="agreed to meet")

    text = store.summary_for("Emma Harris", _world(
        minutes=15 * 60,
        locations={"Emma Harris": "Park.Bench", "Adam Harris": "Park.Tree"},
        holdings={"Emma Harris": {"cold_medicine": 1}}))

    assert "is right here with you" in text          # 点名物品的那条留下
    assert "You are with Adam Harris right now" not in text


def test_two_different_people_each_get_their_own_line(store):
    """去重是按人去的，不是按"说过一次就不说了"。"""
    store.accept("Emma Harris", DELIVER, "Adam Harris", "cold_medicine",
                 deadline_minute=18 * 60, life_day=1, reason="Adam is ill")
    store.accept("Emma Harris", MEET, "Mia Thompson", "Park",
                 deadline_minute=15 * 60, life_day=1, reason="agreed to meet")

    text = store.summary_for("Emma Harris", _world(
        minutes=15 * 60,
        locations={"Emma Harris": "Park.Bench", "Adam Harris": "Park.Tree",
                   "Mia Thompson": "Park.Fountain"},
        holdings={"Emma Harris": {"cold_medicine": 1}}))

    assert "Adam Harris is right here with you" in text
    assert "You are with Mia Thompson right now" in text


# ---------- 窗口不能跟着任务一起消失 ----------

def test_the_window_survives_the_goal_being_settled(store):
    """**这条是两次白跑换来的。**

    决策循环每一步都是先 ``settle`` 再组装上下文，而 MEET 任务在两人到齐
    的那一刻就被判 done——也就是说**窗口打开的那一刻，正是这条任务从眼前
    撤下的那一刻**。第一版把窗口挂在 ``active_for`` 上，条件全都满足，
    只是永远晚了一步：那行字在两整次真跑里出现 **0 次**。
    """
    _agreed_to_meet(store)
    world = _world(minutes=15 * 60,
                   locations={"Arthur Morgan": "Park.Bench",
                              "Mia Thompson": "Park.Tree"},
                   holdings={"Arthur Morgan": {"cake": 1}})

    settled = store.settle("Arthur Morgan", world)
    assert [g.status for g in settled] == ["done"], "前提：碰上面就会被结算掉"
    assert store.active_for("Arthur Morgan", 1) == [], "前提：它已经不在办了"

    assert "You are with Mia Thompson right now" in \
        store.summary_for("Arthur Morgan", world)


def test_a_settled_meeting_is_the_only_thing_left_to_say(store):
    """任务清单空了，窗口仍然要单独出现——不能因为"没有在办的事"就整段返回空。"""
    _agreed_to_meet(store)
    world = _world(minutes=15 * 60,
                   locations={"Arthur Morgan": "Park.Bench",
                              "Mia Thompson": "Park.Tree"},
                   holdings={"Arthur Morgan": {"cake": 1}})
    store.settle("Arthur Morgan", world)

    text = store.summary_for("Arthur Morgan", world)

    assert text.startswith("You are with Mia Thompson right now")
    assert "You have taken on:" not in text


def test_an_expired_meeting_stops_nagging(store):
    """过期作废的约定不该再催——``failed`` 不进窗口。"""
    _agreed_to_meet(store)
    gone = _world(minutes=16 * 60,           # 约的是 15:00，现在 16:00
                  locations={"Arthur Morgan": "Park.Bench"},
                  holdings={"Arthur Morgan": {"cake": 1}})
    settled = store.settle("Arthur Morgan", gone)
    assert [g.status for g in settled] == ["failed"]

    together = _world(minutes=16 * 60,
                      locations={"Arthur Morgan": "Park.Bench",
                                 "Mia Thompson": "Park.Tree"},
                      holdings={"Arthur Morgan": {"cake": 1}})

    assert "right now" not in store.summary_for("Arthur Morgan", together)


def test_a_delivered_errand_does_not_reopen_its_window(store):
    """交完了就别再提。DELIVER 的判定看的是**对方**手上有没有。"""
    store.accept("Emma Harris", DELIVER, "Adam Harris", "cold_medicine",
                 deadline_minute=18 * 60, life_day=1, reason="Adam is ill")
    done = _world(locations={"Emma Harris": "Park.Bench",
                             "Adam Harris": "Park.Tree"},
                  holdings={"Emma Harris": {"cold_medicine": 1},
                            "Adam Harris": {"cold_medicine": 1}})
    store.settle("Emma Harris", done)

    assert "right here with you" not in store.summary_for("Emma Harris", done)


# ---------- 约定的回滚只能收回自己造的那几条 ----------

def test_proposing_the_same_meeting_again_does_not_destroy_it(store):
    """**这条是真跑里踩出来的。**

    重复提议同一个约定时，两边都 already_taken、一条都没新建。第一版按
    "这两个人 + 这个区域 + 这个时刻"模式匹配回滚，于是把**上一次成功约好
    的那对**一起删了：两个人的上下文里那条约定凭空消失，谁也不知道该去见谁,
    而且不报错。记分卡上它和"模型没做到"长得一模一样。
    """
    assert store.arrange_meeting("Arthur Morgan", "Mia Thompson", "Park",
                                 15 * 60, 1, "first")["ok"]

    again = store.arrange_meeting("Arthur Morgan", "Mia Thompson", "Park",
                                  15 * 60, 1, "又说了一遍")

    assert again["ok"] is False and again["reason"] == "already_taken"
    assert store.meeting_record()["arranged"] == 1, "原来那对必须还在"
    assert [g.describe() for g in store.active_for("Arthur Morgan", 1)]
    assert [g.describe() for g in store.active_for("Mia Thompson", 1)]


def test_a_meeting_the_other_side_cannot_take_leaves_nothing_behind(store):
    """回滚本身要照旧管用：一方排不下就一条都不留，**绝不留单边约定**。"""
    # 把 Mia 的 MEET 名额占满。地点要不一样——重复判定看的是"同一个人 +
    # 同一个地点"，不看时刻，同地点第二次会被当成重复而不是占名额。
    for area, hour in (("Park", 9), ("Supermarket", 11)):
        assert store.arrange_meeting("Mia Thompson", "Adam Harris", area,
                                     hour * 60, 1, "已有的约")["ok"]

    blocked = store.arrange_meeting("Arthur Morgan", "Mia Thompson", "Cafe_bar",
                                    15 * 60, 1, "Mia 排不下了")

    assert blocked["ok"] is False and blocked["reason"] == "too_many"
    assert not [g for g in store.active_for("Arthur Morgan", 1)], \
        "Arthur 那一半必须收回，否则他会以为约好了"
    assert len(store.active_for("Mia Thompson", 1)) == 2, "她原有的两个约不该受牵连"
