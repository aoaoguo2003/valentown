"""世界规则与感知的单元测试：营业时间、顾客容量、在场判定，
以及最要紧的一条——信息不对称（居民看不见远处的人，拒绝理由也不泄露去向）。
不涉及任何 LLM 调用。"""

from agents.agent import RonParker, EmmaHarris
from memory.memory_system import MemorySystem
from tools import get_tool
from world import (
    CUSTOMER_CAPACITY,
    OPENING_HOURS,
    SHOP_OWNERS,
    World,
    area_of,
    format_clock,
)


def _minutes(hour, minute=0):
    return hour * 60 + minute


def _make_agent(tmp_path, cls=RonParker, location="Ron_home.Living_room"):
    memory = MemorySystem(retention_days=15, memory_dir=tmp_path)
    memory.initialize_agents(["Ron Parker", "Emma Harris"])
    return cls(memory, location)


def _move(agent, world, destination, action="do something", talk_to="nobody", minutes=60):
    return get_tool("move_to").handler(
        agent,
        {
            "action": action,
            "destination": destination,
            "duration_minutes": minutes,
            "talk_to": talk_to,
        },
        world,
    )


# ---------- 信息不对称：这是整层设计的核心约束 ----------

def test_visible_agents_only_covers_the_same_area():
    world = World(time_minutes=_minutes(14), agent_locations={
        "Ron Parker": "Café_bar.Counter",
        "Ella Parker": "Café_bar.Window_seat",   # 同区域，看得见
        "Emma Harris": "Park.Bench",             # 别处，看不见
        "Mia Thompson": "Mia_home.Kitchen",      # 别处，看不见
    })
    assert world.visible_agents("Ron Parker") == ["Ella Parker"]
    # 反过来也一样：公园里的人看不见咖啡馆里的人。
    assert world.visible_agents("Emma Harris") == []


def test_rejection_never_reveals_where_the_target_is(tmp_path):
    # 想找的人不在，只能被告知"不在这儿"——绝不能顺带说出对方的去向，
    # 否则等于白送一份全局位置表，通信也就没有存在的必要了。
    agent = _make_agent(tmp_path)
    world = World(time_minutes=_minutes(14), agent_locations={
        "Ron Parker": "Ron_home.Living_room",
        "Emma Harris": "Park.Playground",        # 她在公园
    })

    result = _move(agent, world, "Café_bar.Counter", talk_to="Emma Harris")

    assert result["ok"] is False
    assert result["reason"] == "target_absent"
    assert "Emma Harris" in result["observation"]
    # 关键断言：反馈里不能出现她真正所在的区域。
    assert "Park" not in result["observation"]
    assert "Playground" not in result["observation"]


def test_arrival_observation_only_names_people_actually_present(tmp_path):
    # 到达之后本人就在现场，看得见的人可以说；别处的人不能出现。
    agent = _make_agent(tmp_path)
    world = World(time_minutes=_minutes(14), agent_locations={
        "Ron Parker": "Ron_home.Living_room",
        "Ella Parker": "Café_bar.Patio",         # 目的地区域内
        "Emma Harris": "Park.Bench",             # 别处
    })

    result = _move(agent, world, "Café_bar.Counter")

    assert result["ok"] is True
    assert "Ella Parker" in result["observation"]
    assert "Emma Harris" not in result["observation"]


# ---------- 营业时间 ----------

def test_closed_shop_is_rejected_with_its_hours(tmp_path):
    agent = _make_agent(tmp_path, EmmaHarris, "Emma_home.Living_room")
    world = World(time_minutes=_minutes(20), agent_locations={})   # 晚上八点

    result = _move(agent, world, "Pharmacy.Medicine_shelf")

    assert result["ok"] is False
    assert result["reason"] == "closed"
    # 拒绝要给出可行动的信息：几点开门。
    assert "9:00 AM" in result["observation"]
    assert "6:00 PM" in result["observation"]


def test_shop_open_during_hours(tmp_path):
    agent = _make_agent(tmp_path, EmmaHarris, "Emma_home.Living_room")
    world = World(time_minutes=_minutes(10), agent_locations={})
    assert _move(agent, world, "Pharmacy.Medicine_shelf")["ok"] is True


def test_owner_may_enter_own_shop_outside_hours(tmp_path):
    # 店主可以提前来备货；这也让"店主"这个身份在规则里真的有意义。
    ron = _make_agent(tmp_path)                       # Ron 经营超市
    world = World(time_minutes=_minutes(6), agent_locations={})

    assert SHOP_OWNERS["Supermarket"] == "Ron Parker"
    assert _move(ron, world, "Supermarket.Checkout")["ok"] is True
    # 但别人家的店照样进不去。
    assert _move(ron, world, "Pharmacy.Medicine_shelf")["ok"] is False


def test_park_and_home_are_always_open(tmp_path):
    agent = _make_agent(tmp_path)
    world = World(time_minutes=_minutes(3), agent_locations={})   # 凌晨三点
    assert _move(agent, world, "Park.Bench")["ok"] is True
    assert _move(agent, world, "Ron_home.Kitchen")["ok"] is True


# ---------- 顾客容量 ----------

def test_shop_full_at_three_customers(tmp_path):
    agent = _make_agent(tmp_path, EmmaHarris, "Emma_home.Living_room")
    assert CUSTOMER_CAPACITY == 3
    world = World(time_minutes=_minutes(14), agent_locations={
        "Mia Thompson": "Café_bar.Counter",
        "Arthur Morgan": "Café_bar.Window_seat",
        "Gavin Harris": "Café_bar.Patio",
    })

    result = _move(agent, world, "Café_bar.Corner_table")

    assert result["ok"] is False
    assert result["reason"] == "full"
    # 挤不进去是到门口才发现的，所以现场有谁可以说。
    assert "Mia Thompson" in result["observation"]


def test_owner_does_not_consume_a_customer_slot(tmp_path):
    # 超市里有店主 Ron 加两位顾客，第三位顾客仍进得去。
    agent = _make_agent(tmp_path, EmmaHarris, "Emma_home.Living_room")
    world = World(time_minutes=_minutes(14), agent_locations={
        "Ron Parker": "Supermarket.Boss",         # 店主
        "Mia Thompson": "Supermarket.Checkout",
        "Arthur Morgan": "Supermarket.Fruit_shelf",
    })
    assert world.customer_count("Supermarket") == 2
    assert _move(agent, world, "Supermarket.Entrance_aisle")["ok"] is True


def test_owner_always_has_room_in_own_shop(tmp_path):
    ron = _make_agent(tmp_path)
    world = World(time_minutes=_minutes(14), agent_locations={
        "Mia Thompson": "Supermarket.Checkout",
        "Arthur Morgan": "Supermarket.Fruit_shelf",
        "Emma Harris": "Supermarket.Storage",     # 顾客已满
    })
    assert _move(ron, world, "Supermarket.Boss")["ok"] is True


def test_park_has_no_capacity_limit(tmp_path):
    agent = _make_agent(tmp_path)
    world = World(time_minutes=_minutes(14), agent_locations={
        name: "Park.Bench" for name in
        ["Ella Parker", "Emma Harris", "Gavin Harris", "Mia Thompson", "Arthur Morgan"]
    })
    assert _move(agent, world, "Park.Tree")["ok"] is True


# ---------- 在场判定 ----------

def test_talking_to_someone_in_the_same_area_succeeds(tmp_path):
    # 同区域即可交谈，不要求挤在同一个锚点。
    agent = _make_agent(tmp_path)
    world = World(time_minutes=_minutes(14), agent_locations={
        "Emma Harris": "Café_bar.Patio",
    })
    assert _move(agent, world, "Café_bar.Counter", talk_to="Emma Harris")["ok"] is True


def test_structural_validation_still_applies(tmp_path):
    # 环境规则是加在结构校验之后的，原有的硬拒绝与软修复行为不变。
    agent = _make_agent(tmp_path)
    world = World(time_minutes=_minutes(14), agent_locations={})

    assert _move(agent, world, "Ella_home.Bed")["ok"] is False          # 卧室不在白名单
    assert _move(agent, world, "Park.Bench", action="  ")["ok"] is False  # 动作为空

    clamped = _move(agent, world, "Park.Bench", minutes=9999)
    assert clamped["ok"] is True
    assert clamped["decision"]["duration_minutes"] == 180                # 越界被夹住

    self_talk = _move(agent, world, "Park.Bench", talk_to="Ron Parker")  # 自己和自己说话
    assert self_talk["decision"]["talk_to"] == "nobody"


# ---------- 辅助函数 ----------

def test_area_of_and_format_clock():
    assert area_of("Café_bar.Counter") == "Café_bar"
    assert area_of("Ron_home.Kitchen") == "Ron_home"
    assert format_clock(0) == "12:00 AM"
    assert format_clock(_minutes(9, 5)) == "9:05 AM"
    assert format_clock(_minutes(12)) == "12:00 PM"
    assert format_clock(_minutes(21, 30)) == "9:30 PM"


def test_opening_hours_cover_every_commercial_area():
    # 三家店都要有营业时间；公园和住宅刻意不在表里。
    assert set(OPENING_HOURS) == {"Café_bar", "Supermarket", "Pharmacy"}
    for area, (start, end) in OPENING_HOURS.items():
        assert 0 <= start < end <= 24 * 60, area


# ---------- stay：留在原地 ----------

def _stay(agent, world, action="carry on", talk_to="nobody", minutes=60):
    return get_tool("stay").handler(
        agent,
        {"thought": "because", "action": action, "duration_minutes": minutes, "talk_to": talk_to},
        world,
    )


def test_stay_keeps_you_where_you_are(tmp_path):
    agent = _make_agent(tmp_path, location="Café_bar.Counter")
    world = World(time_minutes=_minutes(14), agent_locations={"Ron Parker": "Café_bar.Counter"})

    result = _stay(agent, world, action="finish my coffee")

    assert result["ok"] is True
    assert result["decision"]["destination"] == "Café_bar.Counter"
    assert "stay" in result["observation"].lower()


def test_stay_ignores_capacity_because_the_seat_is_already_yours(tmp_path):
    # 店里顾客已满（含自己），继续待着不该被自己挤掉。
    agent = _make_agent(tmp_path, location="Café_bar.Counter")
    world = World(time_minutes=_minutes(14), agent_locations={
        "Ron Parker": "Café_bar.Counter",
        "Mia Thompson": "Café_bar.Window_seat",
        "Arthur Morgan": "Café_bar.Patio",
    })

    assert world.customer_count("Café_bar") == 3            # 已经满员
    assert _stay(agent, world)["ok"] is True                # 但自己待得住


def test_stay_still_respects_closing_time(tmp_path):
    # 打烊了就待不住了——这会逼出一次重新规划。
    agent = _make_agent(tmp_path, location="Café_bar.Counter")
    world = World(time_minutes=_minutes(23), agent_locations={"Ron Parker": "Café_bar.Counter"})

    result = _stay(agent, world, action="linger over my drink")

    assert result["ok"] is False
    assert result["reason"] == "closed"
    assert "cannot stay" in result["observation"]


def test_stay_at_home_is_always_allowed(tmp_path):
    agent = _make_agent(tmp_path, location="Ron_home.Sofa")
    world = World(time_minutes=_minutes(3), agent_locations={"Ron Parker": "Ron_home.Sofa"})
    assert _stay(agent, world, action="doze on the sofa")["ok"] is True


def test_stay_rejects_talking_to_someone_who_left(tmp_path):
    # 想搭话的人已经不在，而且反馈同样不能透露对方去向。
    agent = _make_agent(tmp_path, location="Café_bar.Counter")
    world = World(time_minutes=_minutes(14), agent_locations={
        "Ron Parker": "Café_bar.Counter",
        "Emma Harris": "Park.Bench",
    })

    result = _stay(agent, world, talk_to="Emma Harris")

    assert result["ok"] is False
    assert result["reason"] == "target_absent"
    assert "Park" not in result["observation"]


def test_stay_uses_the_world_snapshot_over_stale_local_state(tmp_path):
    # 前端同步上来的位置是更准的那份，快照优先于后端记录。
    agent = _make_agent(tmp_path, location="Ron_home.Living_room")
    world = World(time_minutes=_minutes(14), agent_locations={"Ron Parker": "Park.Bench"})

    result = _stay(agent, world, action="watch the river")

    assert result["decision"]["destination"] == "Park.Bench"


def test_stay_needs_no_destination_parameter():
    # 参数空间的差距就是省下的 token 与选错地方的机会。
    stay = get_tool("stay")
    move_to = get_tool("move_to")
    assert "destination" not in stay.parameters["properties"]
    assert len(move_to.parameters["properties"]["destination"]["enum"]) > 100
    assert stay.terminal is True                            # 消耗时间，收敛本轮


# ---------- 工具可见性：只按「永远不可用」筛，不按「此刻不可用」筛 ----------

def test_only_shopkeepers_are_shown_restock():
    from tools import function_schemas

    ron = [s["function"]["name"] for s in function_schemas("Ron Parker")]
    ella = [s["function"]["name"] for s in function_schemas("Ella Parker")]
    emma = [s["function"]["name"] for s in function_schemas("Emma Harris")]

    assert "restock" in ron and "restock" in ella
    assert "restock" not in emma        # 她一辈子也补不了货，摆给她只有坏处


def test_capabilities_blocked_only_by_circumstance_stay_visible():
    """⚠️ 这条最容易被后人改错。

    "要在店里才能买"是**临时**门槛，绝不能拿来过滤工具——看不见的能力，
    模型不会为它做计划：Emma 在家看不到 buy，就不会想到"我得去药房"。
    **能力的可见性是规划的前提。**
    """
    from tools import function_schemas

    # Emma 此刻在家，什么都买不了、给不了、也没钱转——但这些工具必须都在。
    visible = [s["function"]["name"] for s in function_schemas("Emma Harris")]
    for name in ["buy", "check_stock", "give_item", "transfer", "move_to"]:
        assert name in visible, name


def test_eligibility_defaults_to_everyone():
    from tools import TOOL_REGISTRY

    restricted = [name for name, spec in TOOL_REGISTRY.items() if spec.eligible is not None]
    assert restricted == ["restock"]     # 目前只有这一件有永久门槛

    for name, spec in TOOL_REGISTRY.items():
        if name != "restock":
            assert spec.is_eligible("Adam Harris") is True, name


def test_a_non_owner_is_still_refused_at_the_handler(tmp_path, monkeypatch):
    """白名单是省 token 的，**不是安全边界**——handler 的检查一个都不能省。

    schema 里看不见只是让模型不会去选；真有谁绕过去直接调，拒绝仍然发生
    在 handler 里。两道防线各管一件事：一道省钱，一道保证正确。
    """
    from economy import Economy
    from tools import get_tool

    monkeypatch.setattr("economy.economy", Economy(path=tmp_path / "e.json"))
    emma = _make_agent(tmp_path, EmmaHarris, "Supermarket.Checkout")
    world = World(time_minutes=_minutes(10),
                  agent_locations={"Emma Harris": "Supermarket.Checkout"})

    assert get_tool("restock").is_eligible("Emma Harris") is False
    result = get_tool("restock").handler(
        emma, {"thought": "helping out", "item": "bread", "quantity": 1}, world)
    assert result["ok"] is False
    assert result["reason"] == "not_the_owner"


# ---------- sleep：唯一能横跨整夜的动作 ----------

def _sleep(agent, world, minutes=480):
    return get_tool("sleep").handler(
        agent, {"thought": "long day", "duration_minutes": minutes}, world)


def test_sleep_can_run_far_past_the_normal_action_cap(tmp_path):
    # 普通动作最长 180 分钟，睡到天亮要八九个小时——没有这个工具的话，
    # 模型得连着决策三次才能睡过一夜，每次都是一整轮 LLM 调用。
    from tools.locations import MAX_ACTION_MINUTES, MAX_SLEEP_MINUTES

    agent = _make_agent(tmp_path, location="Ron_home.Sofa")
    world = World(time_minutes=22 * 60, agent_locations={"Ron Parker": "Ron_home.Sofa"})

    result = _sleep(agent, world, 510)

    assert result["ok"] is True
    assert result["decision"]["duration_minutes"] == 510
    assert 510 > MAX_ACTION_MINUTES              # 远超普通动作的上限
    assert MAX_SLEEP_MINUTES == 720


def test_absurd_durations_are_clamped_not_honoured(tmp_path):
    # 不设上限的话，一个动作时长会直接变成世界时钟往前跳的幅度。
    agent = _make_agent(tmp_path, location="Ron_home.Sofa")
    world = World(time_minutes=22 * 60, agent_locations={"Ron Parker": "Ron_home.Sofa"})

    assert _sleep(agent, world, 99999)["decision"]["duration_minutes"] == 720
    assert _sleep(agent, world, 1)["decision"]["duration_minutes"] == 30


def test_you_can_only_sleep_at_your_own_home(tmp_path):
    # 不是道德要求，是因为床在家里。
    agent = _make_agent(tmp_path, location="Park.Bench")
    world = World(time_minutes=22 * 60, agent_locations={"Ron Parker": "Park.Bench"})

    result = _sleep(agent, world)

    assert result["ok"] is False
    assert result["reason"] == "not_at_home"
    assert "Ron_home" in result["observation"]   # 告诉它该回哪儿


def test_sleeping_in_someone_elses_house_is_refused(tmp_path):
    agent = _make_agent(tmp_path, location="Ella_home.Sofa")
    world = World(time_minutes=22 * 60, agent_locations={"Ron Parker": "Ella_home.Sofa"})

    assert _sleep(agent, world)["reason"] == "not_at_home"


def test_sleep_action_text_triggers_the_energy_reset(tmp_path):
    # agent_state 靠关键词判断这次动作算不算休息。有了这个工具之后，
    # 那个判断第一次有了明确来源，而不是从自由文本里猜。
    from agent_state import is_sleep_action

    agent = _make_agent(tmp_path, location="Ron_home.Sofa")
    world = World(time_minutes=22 * 60, agent_locations={"Ron Parker": "Ron_home.Sofa"})

    decision = _sleep(agent, world)["decision"]

    assert is_sleep_action(decision["destination"], decision["action"]) is True


def test_sleep_ends_the_turn(tmp_path):
    # 它占用游戏时间，所以必须收敛本轮——而且是三个 terminal 工具之一。
    from tools import TOOL_REGISTRY

    assert get_tool("sleep").terminal is True
    terminal = sorted(n for n, s in TOOL_REGISTRY.items() if s.terminal)
    assert terminal == ["move_to", "sleep", "stay"]
