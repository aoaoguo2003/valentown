"""Unit tests for the deterministic core: clock parsing, need triggers, and
the agent-specific rolling memory bank. These run without any Claude calls."""

from agent_state import (
    DEFAULT_STATE,
    clamp_state_values,
    evaluate_agent_triggers,
    parse_clock_to_minutes,
    to_game_minute,
)
from memory.memory_system import MemorySystem, ReflectionRecord


def test_parse_clock_to_minutes_handles_am_pm_and_noon_midnight():
    assert parse_clock_to_minutes("6:30 AM") == 6 * 60 + 30
    assert parse_clock_to_minutes("12:00 AM") == 0          # midnight
    assert parse_clock_to_minutes("12:00 PM") == 12 * 60    # noon
    assert parse_clock_to_minutes("9 PM") == 21 * 60
    assert parse_clock_to_minutes("garbage") == 6 * 60      # safe fallback


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
    # energy (priority 90) outranks hunger (80) outranks social (65).
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
    # Ella's memory must not leak into Ron's bank.
    assert all("Ella" not in record.content for record in ron)


def test_memory_retention_prunes_old_life_days(tmp_path):
    memory = MemorySystem(retention_days=15, memory_dir=tmp_path)
    memory.initialize_agents(["Ron Parker"])
    memory.add_memory("Ron Parker: ancient event", "daily_plan", 5, agent_name="Ron Parker", life_day=1)
    memory.add_memory("Ron Parker: recent event", "daily_plan", 5, agent_name="Ron Parker", life_day=20)

    # current day 20, retention 15 -> day 1 (< 6) is pruned out.
    memory.set_life_day(20, ["Ron Parker"])
    contents = [record.content for record in memory.get_memories(agent_name="Ron Parker")]
    assert "Ron Parker: recent event" in contents
    assert "Ron Parker: ancient event" not in contents


def test_reflection_record_serializes_with_level(tmp_path):
    memory = MemorySystem(retention_days=15, memory_dir=tmp_path)
    memory.initialize_agents(["Ron Parker"])
    base = memory.add_memory("Ron Parker: played chess", "daily_plan", 5, agent_name="Ron Parker")
    reflection = ReflectionRecord("Ron Parker: Reflection: enjoys strategy", [base], level=1, agent_name="Ron Parker")
    memory.add_reflection(reflection, agent_name="Ron Parker")

    reflections = memory.get_recent_reflections("Ron Parker")
    assert len(reflections) == 1
    assert reflections[0].category == "reflection"
