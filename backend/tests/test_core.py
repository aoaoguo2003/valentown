"""确定性核心逻辑的单元测试：时钟解析、需求触发、按智能体隔离的滚动记忆库，
以及由需求驱动的决策兜底逻辑。这些测试不涉及任何 LLM 调用。"""

from agents.state import (
    DEFAULT_STATE,
    clamp_state_values,
    evaluate_agent_triggers,
    parse_clock_to_minutes,
    to_game_minute,
)
from agents.agent import ALLOWED_DESTINATIONS, AGENT_NAMES, RonParker
from memory.memory_system import MemorySystem, ReflectionRecord


def test_parse_clock_to_minutes_handles_am_pm_and_noon_midnight():
    assert parse_clock_to_minutes("6:30 AM") == 6 * 60 + 30
    assert parse_clock_to_minutes("12:00 AM") == 0          # 午夜
    assert parse_clock_to_minutes("12:00 PM") == 12 * 60    # 正午
    assert parse_clock_to_minutes("9 PM") == 21 * 60
    assert parse_clock_to_minutes("garbage") == 6 * 60      # 安全兜底值


def test_to_game_minute_offsets_by_day():
    assert to_game_minute(day=1, time="6:00 AM") == 6 * 60
    assert to_game_minute(day=2, time="6:00 AM") == 24 * 60 + 6 * 60


def test_clamp_state_values_bounds_to_0_100():
    state = {"values": {"hunger": 150, "energy": -10, "social": 50.6}}
    clamp_state_values(state)
    assert state["values"] == {"hunger": 100, "energy": 0, "social": 51}


def test_evaluate_triggers_fires_and_sorts_by_priority():
    state = {
        "values": {"hunger": 90, "energy": 10, "social": 10},
        "thresholds": DEFAULT_STATE["thresholds"],
        "trigger_preferences": DEFAULT_STATE["trigger_preferences"],
    }
    triggers = evaluate_agent_triggers(state)
    needs = [trigger["need"] for trigger in triggers]
    assert set(needs) == {"hunger", "energy", "social"}
    # energy（优先级 90）高于 hunger（80），hunger 又高于 social（65）。
    assert needs == ["energy", "hunger", "social"]


def test_evaluate_triggers_quiet_when_needs_satisfied():
    state = {
        "values": {"hunger": 10, "energy": 90, "social": 90},
        "thresholds": DEFAULT_STATE["thresholds"],
        "trigger_preferences": DEFAULT_STATE["trigger_preferences"],
    }
    assert evaluate_agent_triggers(state) == []


def test_memory_bank_roundtrip_and_agent_isolation(tmp_path):
    memory = MemorySystem(retention_days=15, memory_dir=tmp_path)
    memory.initialize_agents(["Ron Parker", "Ella Parker"])
    memory.set_life_day(1, ["Ron Parker", "Ella Parker"])

    memory.add_memory("Ron Parker: opened the shop", "daily_plan", 5, agent_name="Ron Parker")
    memory.add_memory("Ella Parker: filled prescriptions", "daily_plan", 5, agent_name="Ella Parker")

    ron = memory.get_memories(agent_name="Ron Parker")
    assert len(ron) == 1
    assert ron[0].agent_name == "Ron Parker"
    # Ella 的记忆不能泄漏进 Ron 的记忆库。
    assert all("Ella" not in record.content for record in ron)


def test_memory_retention_prunes_old_life_days(tmp_path):
    memory = MemorySystem(retention_days=15, memory_dir=tmp_path)
    memory.initialize_agents(["Ron Parker"])
    memory.add_memory("Ron Parker: ancient event", "daily_plan", 5, agent_name="Ron Parker", life_day=1)
    memory.add_memory("Ron Parker: recent event", "daily_plan", 5, agent_name="Ron Parker", life_day=20)

    # 当前是第 20 天，保留期为 15 天 -> 第 1 天（< 6）会被清理掉。
    memory.set_life_day(20, ["Ron Parker"])
    contents = [record.content for record in memory.get_memories(agent_name="Ron Parker")]
    assert "Ron Parker: recent event" in contents
    assert "Ron Parker: ancient event" not in contents


def _make_agent(tmp_path):
    memory = MemorySystem(retention_days=15, memory_dir=tmp_path)
    memory.initialize_agents(["Ron Parker"])
    return RonParker(memory, "Ron_home.Living_room")


def test_allowed_destinations_exclude_private_rooms():
    # 隐私保护是通过设计强制实现的：LLM 可选择的目的地清单中
    # 不存在卧室/卫生间这类锚点。
    assert not any(dest.endswith(".Bed") for dest in ALLOWED_DESTINATIONS)
    assert not any(dest.endswith(".Toilet") for dest in ALLOWED_DESTINATIONS)
    assert "Park.Bench" in ALLOWED_DESTINATIONS
    assert "Ron_home.Kitchen" in ALLOWED_DESTINATIONS


def test_fallback_decision_honours_top_trigger(tmp_path):
    agent = _make_agent(tmp_path)

    hungry = agent.fallback_next_action([{"need": "hunger"}])
    assert hungry["destination"] == "Ron_home.Kitchen"

    tired = agent.fallback_next_action([{"need": "energy"}])
    assert tired["destination"] == "Ron_home.Sofa"

    lonely = agent.fallback_next_action([{"need": "social"}])
    assert lonely["destination"] == "Park.Bench"

    idle = agent.fallback_next_action([])
    assert idle["destination"] in ALLOWED_DESTINATIONS


def test_the_town_roster_is_exactly_seven_people(tmp_path):
    # 花名册是很多东西的取值范围：talk_to 的候选、收信人白名单、
    # 转账对象。多一个少一个都会让某个 schema 悄悄变形。
    assert set(AGENT_NAMES) == {
        "Ron Parker", "Ella Parker", "Emma Harris", "Gavin Harris",
        "Adam Harris", "Mia Thompson", "Arthur Morgan"
    }


def test_reflection_record_serializes_with_level(tmp_path):
    memory = MemorySystem(retention_days=15, memory_dir=tmp_path)
    memory.initialize_agents(["Ron Parker"])
    base = memory.add_memory("Ron Parker: played chess", "daily_plan", 5, agent_name="Ron Parker")
    reflection = ReflectionRecord("Ron Parker: Reflection: enjoys strategy", [base], level=1, agent_name="Ron Parker")
    memory.add_reflection(reflection, agent_name="Ron Parker")

    reflections = memory.get_recent_reflections("Ron Parker")
    assert len(reflections) == 1
    assert reflections[0].category == "reflection"
