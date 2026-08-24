"""并发验证：七个居民能不能真的同时等外部调用。

前端对每个居民分别发请求且互不等待，Flask 以多线程处理，所以理论上
七次 LLM 调用可以重叠。但"理论上"不算数——**只要有一把锁跨住了那次网络
往返，七个人就会退回串行**，而这正是改造前的样子（整个决策包在
state_lock 里）。

这里用假 LLM + 固定延时代替真实网络：不花钱、不看网速，却能把"锁的粒度
有没有毁掉并发"这件事量出来。GIL 在这里不构成障碍——I/O 等待期间它会被
释放，所以线程能重叠等待；GIL 挡的是 CPU 并行，不是 I/O 并发。
"""

import threading
import time

import pytest

from agents.agent import (
    AdamHarris,
    ArthurMorgan,
    EllaParker,
    EmmaHarris,
    GavinHarris,
    MiaThompson,
    RonParker,
)
from memory.memory_system import MemorySystem
from runtime import run_decision_loop
from world import World

# 单次"网络调用"的模拟耗时。取值要够大以盖过调度噪声，
# 又够小以免拖慢测试。
CALL_SECONDS = 0.20
AGENT_COUNT = 7


def _build_agents(tmp_path):
    memory = MemorySystem(retention_days=15, memory_dir=tmp_path)
    classes = [RonParker, EllaParker, EmmaHarris, GavinHarris,
               AdamHarris, MiaThompson, ArthurMorgan]
    agents = [cls(memory, "Park.Bench") for cls in classes]
    memory.initialize_agents([agent.name for agent in agents])
    return agents


def _slow_llm(agent, destination):
    """假 LLM：睡一会儿模拟网络往返，然后返回一个必定通过的动作。"""
    def call_tools(agent_name, context, tool_schemas):
        time.sleep(CALL_SECONDS)
        return {
            "name": "move_to",
            "args": {
                "thought": "somewhere quiet",
                "action": "sit and think",
                "destination": destination,
                "duration_minutes": 60,
                "talk_to": "nobody",
            },
        }
    agent.llm.call_tools = call_tools


def _shared_world_provider():
    """贴近 main.py 的真实形态：每次进锁都新建一份世界快照。

    锁是真的——如果决策路径里有哪一步在持锁状态下做慢 I/O，
    这把锁就会把七个线程串起来，耗时立刻暴露出来。
    """
    lock = threading.Lock()

    def with_world(fn):
        with lock:
            return fn(World(time_minutes=14 * 60, agent_locations={}))

    return with_world


def _run_all(agents, with_world):
    barrier = threading.Barrier(len(agents))
    errors = []

    def drive(agent):
        barrier.wait()                       # 让七个线程尽量同时起跑
        try:
            run_decision_loop(
                agent,
                internal_state={"values": {"hunger": 40, "energy": 70, "social": 60}},
                triggers=[],
                day_number=1,
                time_text="2:00 PM",
                current_location="Park.Bench",
                last_action="woke up",
                with_world=with_world,
            )
        except Exception as error:           # noqa: BLE001  测试里要看到任何异常
            errors.append(error)

    threads = [threading.Thread(target=drive, args=(agent,)) for agent in agents]
    started = time.monotonic()
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    elapsed = time.monotonic() - started

    assert not errors, errors
    return elapsed


def test_seven_residents_wait_on_the_api_at_the_same_time(tmp_path):
    """七个居民并发决策的总耗时，应当接近**一次**调用而不是七次。

    串行的话是 7 x 0.20 = 1.40 秒；并发的话约 0.20 秒。断言留了三倍以上
    余量，够区分这两种情况，也不会因为机器慢而误报。
    """
    agents = _build_agents(tmp_path)
    for index, agent in enumerate(agents):
        _slow_llm(agent, f"Park.{['Bench', 'Chair', 'Tree', 'River', 'Bridge', 'Playground', 'Flower_bed'][index]}")

    elapsed = _run_all(agents, _shared_world_provider())

    serial = CALL_SECONDS * AGENT_COUNT
    assert elapsed < serial / 2, (
        f"七个居民用了 {elapsed:.2f}s，串行是 {serial:.2f}s——"
        f"说明有锁跨住了那次网络往返"
    )


def test_the_pre_refactor_shape_would_have_been_serial(tmp_path):
    """反证：把 LLM 调用放回锁内，同一批居民立刻退回串行。

    这正是改造前 main.py 的形态（整个 decide_next_action 包在 state_lock
    里）。留着这个测试是为了证明上一个测试测的是真东西——若两者耗时相同，
    说明并发根本没在发生。
    """
    agents = _build_agents(tmp_path)
    for agent in agents:
        _slow_llm(agent, "Park.Bench")

    lock = threading.Lock()
    barrier = threading.Barrier(len(agents))

    def drive(agent):
        barrier.wait()
        with lock:                                   # ← 慢调用整个包在锁里
            run_decision_loop(
                agent,
                internal_state={"values": {}},
                triggers=[],
                day_number=1,
                time_text="2:00 PM",
                current_location="Park.Bench",
                last_action=None,
                with_world=lambda fn: fn(World(time_minutes=14 * 60, agent_locations={})),
            )

    threads = [threading.Thread(target=drive, args=(agent,)) for agent in agents]
    started = time.monotonic()
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    elapsed = time.monotonic() - started

    serial = CALL_SECONDS * AGENT_COUNT
    assert elapsed >= serial * 0.8, (
        f"锁内做慢调用竟然只用了 {elapsed:.2f}s，本该接近 {serial:.2f}s"
    )


def test_multi_step_loops_also_overlap(tmp_path):
    """多步循环同样重叠——每人两次调用，总耗时仍接近两次而非十四次。

    这一条比单步那条更要紧：改造后一轮最多五次 LLM 调用，如果并发在
    多步路径上失效，锁持有时间就会被放大好几倍。
    """
    agents = _build_agents(tmp_path)

    for index, agent in enumerate(agents):
        seat = ["Bench", "Chair", "Tree", "River", "Bridge", "Playground", "Flower_bed"][index]
        calls = {"n": 0}

        def call_tools(agent_name, context, tool_schemas, calls=calls, seat=seat):
            time.sleep(CALL_SECONDS)
            calls["n"] += 1
            if calls["n"] == 1:                      # 第一步先查记忆（不收敛）
                return {"name": "recall", "args": {"thought": "hmm", "query": "yesterday"}}
            return {
                "name": "move_to",
                "args": {"thought": "settled", "action": "sit down",
                         "destination": f"Park.{seat}", "duration_minutes": 60,
                         "talk_to": "nobody"},
            }

        agent.llm.call_tools = call_tools

    elapsed = _run_all(agents, _shared_world_provider())

    two_calls = CALL_SECONDS * 2
    serial = two_calls * AGENT_COUNT
    assert elapsed < serial / 2, (
        f"两步循环 x 七人用了 {elapsed:.2f}s，串行是 {serial:.2f}s"
    )
    assert elapsed >= two_calls * 0.8, "耗时短得不合理，多步循环可能没真的跑两次"
