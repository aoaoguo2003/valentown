"""天气的单元测试：缓存、重试、熔断、降级，以及户外约束。

天气是这个项目里唯一的真实外部依赖，所以这里的重点不是"天气对不对"，
而是**外部依赖出问题时会发生什么**——超时、限流、返回残缺数据。全部用
故障注入的假 fetcher 完成，一次真实网络请求都不打，所以测试又快又稳。
"""

import threading

import pytest

from agents.agent import RonParker
from memory.memory_system import MemorySystem
from tools import get_tool
from world.locations import OUTDOOR_ANCHORS, is_outdoor
from world.weather import (
    FAILURE_THRESHOLD,
    MAX_RETRIES,
    SEVERE_CODES,
    WeatherService,
    describe,
    is_severe,
)
from world.snapshot import World


@pytest.fixture(autouse=True)
def no_sleeping(monkeypatch):
    """退避真的会 sleep，测试里没必要真等——但仍然记录它被调用了几次。"""
    calls = []
    monkeypatch.setattr("world.weather.time.sleep", lambda seconds: calls.append(seconds))
    return calls


def _clear_sky():
    return [0] * 24


def _agent(tmp_path, location="Ron_home.Living_room"):
    memory = MemorySystem(retention_days=15, memory_dir=tmp_path)
    memory.initialize_agents(["Ron Parker"])
    return RonParker(memory, location)


# ---------- 代码映射 ----------

def test_wmo_codes_map_to_words():
    assert describe(0) == "clear"
    assert describe(65) == "heavy rain"
    assert describe(95) == "thunderstorm"
    assert describe(12345) == "strange weather"


def test_only_genuinely_bad_weather_counts_as_severe():
    # 毛毛雨和小雨不算——撑把伞就行。连小雨都拦的话，居民一个雨天
    # 什么都干不成，约束就成了瘫痪。
    assert is_severe(65) and is_severe(95) and is_severe(82)
    assert not is_severe(0)
    assert not is_severe(51)          # 毛毛雨
    assert not is_severe(61)          # 小雨
    assert not is_severe(3)           # 阴天
    assert SEVERE_CODES.isdisjoint({0, 1, 2, 3, 51, 53, 61, 45})


# ---------- 缓存：外部调用每个游戏日只做一次 ----------

def test_one_call_per_game_day(no_sleeping):
    calls = []

    def fetcher():
        calls.append(1)
        return _clear_sky()

    service = WeatherService(fetcher=fetcher)
    for hour in range(0, 24, 3):
        service.at(life_day=1, time_minutes=hour * 60)

    assert len(calls) == 1            # 八次查询，一次外部调用


def test_a_new_day_fetches_again(no_sleeping):
    calls = []
    service = WeatherService(fetcher=lambda: calls.append(1) or _clear_sky())

    service.at(1, 600)
    service.at(2, 600)

    assert len(calls) == 2


def test_hour_of_day_selects_the_right_slot(no_sleeping):
    codes = list(range(24))           # 每小时一个不同的值
    service = WeatherService(fetcher=lambda: codes)

    assert service.at(1, 0) == 0
    assert service.at(1, 9 * 60 + 30) == 9
    assert service.at(1, 23 * 60) == 23
    assert service.at(1, 99 * 60) == 23        # 越界夹到最后一小时


def test_concurrent_lookups_still_fetch_once(no_sleeping):
    calls = []
    barrier = threading.Barrier(8)

    def fetcher():
        calls.append(1)
        return _clear_sky()

    service = WeatherService(fetcher=fetcher)

    def look():
        barrier.wait()
        service.at(1, 600)

    threads = [threading.Thread(target=look) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(calls) == 1            # 八个居民同时要天气，只打一次外部接口


# ---------- 故障注入：重试、退避、熔断、降级 ----------

def test_transient_failure_is_retried_then_succeeds(no_sleeping):
    attempts = []

    def flaky():
        attempts.append(1)
        if len(attempts) < 3:
            raise TimeoutError("connection timed out")
        return _clear_sky()

    service = WeatherService(fetcher=flaky)
    codes = service.for_day(1)

    assert len(attempts) == 3
    assert codes == _clear_sky()
    assert service.source_for(1) == "live"
    assert len(no_sleeping) == 2      # 失败两次 -> 退避两次


def test_backoff_grows_and_carries_jitter(no_sleeping):
    service = WeatherService(fetcher=lambda: (_ for _ in ()).throw(TimeoutError("nope")))
    service.for_day(1)

    assert len(no_sleeping) == MAX_RETRIES - 1
    # 指数增长：第二次等待明显长于第一次。
    assert no_sleeping[1] > no_sleeping[0]
    # jitter：等待时间不是整齐的 1.0 / 2.0，而是带了随机抖动。
    # 若干个居民同时重试时，抖动把它们的重试时刻散开，避免惊群。
    assert any(round(delay, 6) not in (1.0, 2.0) for delay in no_sleeping)


def test_giving_up_falls_back_instead_of_raising(no_sleeping):
    service = WeatherService(fetcher=lambda: (_ for _ in ()).throw(OSError("network down")))

    codes = service.for_day(1)

    assert len(codes) == 24           # 模拟照常进行，不会因为天气挂掉
    assert service.source_for(1) == "fallback"


def test_short_payload_is_treated_as_a_failure(no_sleeping):
    # 接口返回 200 但数据残缺，同样不能拿来用。
    service = WeatherService(fetcher=lambda: [0, 1, 2])
    service.for_day(1)
    assert service.source_for(1) == "fallback"


def test_circuit_opens_after_repeated_failures(no_sleeping):
    attempts = []

    def dead():
        attempts.append(1)
        raise OSError("network down")

    service = WeatherService(fetcher=dead)
    for day in range(1, FAILURE_THRESHOLD + 4):
        service.for_day(day)

    # 熔断打开后不再白等超时：尝试次数停在阈值 x 重试次数，不随天数增长。
    assert len(attempts) == FAILURE_THRESHOLD * MAX_RETRIES


def test_success_closes_the_circuit_again(no_sleeping):
    state = {"fail": True}

    def flaky():
        if state["fail"]:
            raise OSError("down")
        return _clear_sky()

    service = WeatherService(fetcher=flaky)
    service.for_day(1)                # 失败一次
    state["fail"] = False
    service.for_day(2)                # 恢复
    assert service.source_for(2) == "live"

    state["fail"] = True
    service.for_day(3)                # 计数已清零，会重新尝试而不是直接降级
    assert service.source_for(3) == "fallback"


def test_fallback_weather_is_deterministic(no_sleeping):
    # 用 life_day 做种子而不是真随机：同一天两次查询必须给出同一份天气，
    # 否则模型会看到自相矛盾的世界。
    first = WeatherService(fetcher=lambda: (_ for _ in ()).throw(OSError("x")))
    second = WeatherService(fetcher=lambda: (_ for _ in ()).throw(OSError("x")))

    assert first.for_day(7) == second.for_day(7)
    assert first.for_day(7) != first.for_day(8)


def test_fallback_still_produces_bad_weather_sometimes(no_sleeping):
    # 降级天气必须也会变坏，否则一旦接口挂掉，"下雨改计划"那条分支
    # 就再也走不到了。
    service = WeatherService(fetcher=lambda: (_ for _ in ()).throw(OSError("x")))
    codes = [code for day in range(1, 30) for code in service.for_day(day)]
    assert any(is_severe(code) for code in codes)
    assert any(not is_severe(code) for code in codes)


# ---------- 约束力：天气怎么挡住动作 ----------

def test_outdoor_is_an_anchor_level_property():
    # 同一家店里既有室内也有户外：Patio 是露台，Counter 不是。
    assert is_outdoor("Park.Bench")
    assert is_outdoor("Café_bar.Patio")
    assert not is_outdoor("Café_bar.Counter")
    assert not is_outdoor("Ron_home.Sofa")
    assert "Café_bar.Patio" in OUTDOOR_ANCHORS


def _move(agent, world, destination):
    return get_tool("move_to").handler(
        agent,
        {"thought": "why not", "action": "take a walk", "destination": destination,
         "duration_minutes": 60, "talk_to": "nobody"},
        world,
    )


def test_severe_weather_blocks_outdoor_destinations(tmp_path):
    agent = _agent(tmp_path)
    world = World(time_minutes=14 * 60, agent_locations={}, weather_code=65)   # 大雨

    result = _move(agent, world, "Park.Bench")

    assert result["ok"] is False
    assert result["reason"] == "bad_weather"
    assert "heavy rain" in result["observation"]
    # 反馈要指出可行的方向，模型才知道往哪儿改。
    assert "indoors" in result["observation"]


def test_severe_weather_leaves_indoor_destinations_alone(tmp_path):
    agent = _agent(tmp_path)
    world = World(time_minutes=14 * 60, agent_locations={}, weather_code=95)   # 雷暴

    assert _move(agent, world, "Café_bar.Counter")["ok"] is True
    assert _move(agent, world, "Ron_home.Sofa")["ok"] is True
    # 但同一家店的露台还是不行。
    assert _move(agent, world, "Café_bar.Patio")["ok"] is False


def test_light_rain_does_not_block_anything(tmp_path):
    agent = _agent(tmp_path)
    world = World(time_minutes=14 * 60, agent_locations={}, weather_code=61)   # 小雨

    assert _move(agent, world, "Park.Bench")["ok"] is True


def test_weather_can_drive_you_off_a_bench(tmp_path):
    # 你正在公园坐着，天变了 -> stay 被拒 -> 被赶回室内。
    # 这是唯一会主动把人赶走的力量，和"打烊了待不住"同一个模式。
    agent = _agent(tmp_path, location="Park.Bench")
    world = World(time_minutes=14 * 60, agent_locations={"Ron Parker": "Park.Bench"},
                  weather_code=82)

    result = get_tool("stay").handler(
        agent,
        {"thought": "nice here", "action": "carry on reading",
         "duration_minutes": 60, "talk_to": "nobody"},
        world,
    )

    assert result["ok"] is False
    assert result["reason"] == "bad_weather"


def test_no_weather_in_the_snapshot_blocks_nothing(tmp_path):
    # 快照没带天气时退化为"不设限"，与天气系统接入前的行为一致。
    agent = _agent(tmp_path)
    world = World(time_minutes=14 * 60, agent_locations={})
    assert world.weather_blocks_outdoors() is False
    assert _move(agent, world, "Park.Bench")["ok"] is True


# ---------- check_weather 工具 ----------

def test_forecast_tool_never_touches_the_network(tmp_path, monkeypatch, no_sleeping):
    # 外部调用只在每个游戏日取一次，绝不在裁决动作的路径上发生，
    # 所以这个工具本身永远不会因为网络问题失败。
    calls = []
    service = WeatherService(fetcher=lambda: calls.append(1) or ([0] * 12 + [65] * 12))
    monkeypatch.setattr("world.weather.weather_service", service)

    agent = _agent(tmp_path)
    world = World(time_minutes=10 * 60, agent_locations={}, life_day=1)

    result = get_tool("check_weather").handler(
        agent, {"thought": "planning the afternoon", "hours_ahead": 6}, world)

    assert result["ok"] is True
    assert len(calls) == 1


def test_forecast_warns_about_coming_bad_weather(tmp_path, monkeypatch, no_sleeping):
    # 不查预报的话，模型只知道此刻，于是会在晴天决定出门三小时然后被浇。
    service = WeatherService(fetcher=lambda: [0] * 14 + [65] * 10)
    monkeypatch.setattr("world.weather.weather_service", service)

    agent = _agent(tmp_path)
    world = World(time_minutes=12 * 60, agent_locations={}, life_day=1)

    result = get_tool("check_weather").handler(
        agent, {"thought": "can I picnic", "hours_ahead": 6}, world)

    assert "heavy rain" in result["observation"]
    assert "no good" in result["observation"]           # 明确点出户外不宜的时段


def test_forecast_says_when_nothing_is_coming(tmp_path, monkeypatch, no_sleeping):
    service = WeatherService(fetcher=_clear_sky)
    monkeypatch.setattr("world.weather.weather_service", service)

    agent = _agent(tmp_path)
    world = World(time_minutes=9 * 60, agent_locations={}, life_day=1)

    result = get_tool("check_weather").handler(
        agent, {"thought": "just checking", "hours_ahead": 4}, world)

    assert "should hold" in result["observation"]


def test_check_weather_costs_no_game_time():
    assert get_tool("check_weather").terminal is False
