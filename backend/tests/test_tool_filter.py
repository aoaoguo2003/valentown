"""按此刻状态过滤工具 schema：省的是字，不是能力。

起因是量出来的：一次决策 `prompt_tokens` 中位 4279，而真正的决策上下文
只有约 649 tokens——**输入的 85% 是工具 schema**，而且每次调用一模一样。

做法不是"把用不上的工具藏起来"，而是**把它的完整 schema 换成一行字**：

    buy 的完整 schema        156 tokens
    "buy（要先进店）"          ~11 tokens

⚠️ 为什么非要留那一行：**看不见的能力，模型不会为它做计划。**它只会在
"当下能做什么"里打转，永远不会为了解锁某个能力而先移动。errand 那道题的
唯一出路是写信借钱，而当时 Emma 站在药房里——真把能力藏了，那条路就断了。

最要紧的是最后一组测试：**谓词和 handler 是同一件事写了两遍**，走散的
后果不对称——谓词过严会让模型看不见一件其实能用的工具（丢能力），
过松只是白给一次拒绝（无害）。所以这里拿真 handler 逐条对账。
"""

import tempfile

import pytest
import tools
from agents.agent import EllaParker, EmmaHarris, RonParker
from memory.memory_system import MemorySystem
from world.snapshot import World


def _agent(cls=EmmaHarris, at=None):
    memory = MemorySystem(retention_days=15, memory_dir=tempfile.mkdtemp())
    agent = cls(memory, at or f"{cls.__name__[:-6] if False else 'Emma'}_home.Living_room")
    memory.initialize_agents([agent.name])
    if at:
        agent.current_location = at
    return agent


def _world(locations, **kwargs):
    return World(time_minutes=10 * 60, agent_locations=locations, **kwargs)


# --- 摘掉的是 schema，不是能力 -------------------------------------------------

def test_tools_you_cannot_use_here_leave_the_schema_but_stay_visible():
    emma = _agent(at="Emma_home.Living_room")
    world = _world({"Emma Harris": "Emma_home.Living_room"})

    keep, hidden = tools.schemas_for_now(emma, world)
    kept = {schema["function"]["name"] for schema in keep}
    hidden_names = {name for name, _ in hidden}

    # 在家买不了东西，也没人可以当面递东西
    assert hidden_names == {"buy", "check_stock", "give_item"}
    assert not (kept & hidden_names)
    # 每一条都得说清为什么，否则那行字白花
    assert all(why for _, why in hidden)


def test_standing_in_a_shop_puts_buying_back_on_the_list():
    emma = _agent(at="Pharmacy.Boss")
    world = _world({"Emma Harris": "Pharmacy.Boss"})

    keep, hidden = tools.schemas_for_now(emma, world)
    kept = {schema["function"]["name"] for schema in keep}

    assert "buy" in kept and "check_stock" in kept
    assert "buy" not in {name for name, _ in hidden}


def test_a_shopkeeper_can_read_their_own_ledger_from_anywhere():
    """店主随身带着自己那本账——这条例外 handler 里就有。"""
    ron = _agent(RonParker, at="Park.Bench")
    world = _world({"Ron Parker": "Park.Bench"})

    kept = {s["function"]["name"] for s in tools.schemas_for_now(ron, world)[0]}

    assert "check_stock" in kept       # 账本能远程看
    assert "buy" not in kept           # 但东西不能远程拿


def test_giving_needs_both_something_to_give_and_someone_to_give_it_to():
    emma = _agent(at="Park.Bench")
    alone = _world({"Emma Harris": "Park.Bench"})
    together = _world({"Emma Harris": "Park.Bench", "Mia Thompson": "Park.Tree"})

    import world.economy as economy_module

    economy_module.economy.seed(holdings={"Emma Harris": {"cake": 1}})
    try:
        assert "give_item" in {n for n, _ in tools.schemas_for_now(emma, alone)[1]}
        assert "give_item" not in {n for n, _ in tools.schemas_for_now(emma, together)[1]}
    finally:
        economy_module.economy.seed(holdings={"Emma Harris": {}})


def test_the_turn_can_always_still_be_ended():
    """``move_to`` / ``stay`` 没有谓词，所以本轮**至少还剩一个收敛点**。

    真把它们摘光了，这一轮无论如何都做不出动作——不会报错，只会 100% 兜底。
    """
    for where in ("Emma_home.Living_room", "Park.Bench", "Pharmacy.Boss"):
        emma = _agent(at=where)
        kept = {s["function"]["name"]
                for s in tools.schemas_for_now(emma, _world({"Emma Harris": where}))[0]}
        assert {"move_to", "stay"} <= kept, f"在 {where} 连收敛点都被摘了"


def test_filtering_actually_saves_most_of_what_the_full_schema_costs():
    """省下来的必须**远大于**那一行字的开销，否则这件事不值得做。"""
    import json

    emma = _agent(at="Emma_home.Living_room")
    world = _world({"Emma Harris": "Emma_home.Living_room"})

    full = tools.function_schemas(emma.name)
    keep, hidden = tools.schemas_for_now(emma, world)
    size = lambda schemas: len(json.dumps(schemas, ensure_ascii=False))   # noqa: E731
    line = "; ".join(f"{name} ({why})" for name, why in hidden)

    saved = size(full) - size(keep)
    assert saved > 4 * len(line), "省下的还不到那行字的四倍，不划算"


# --- 上下文里必须留下痕迹 ------------------------------------------------------

def test_the_hidden_tools_are_named_in_the_context_and_marked_as_still_possible():
    emma = _agent(at="Emma_home.Living_room")

    context = emma.build_decision_context(
        internal_state={"values": {}}, triggers=[], day_number=1,
        time_text="10:00 AM", current_location="Emma_home.Living_room",
        hidden_tools=[("buy", "you have to be standing inside a shop")],
    )

    assert "buy" in context
    assert "you have to be standing inside a shop" in context
    # 关键的一句：它们还在，只是得先满足条件
    assert "still exist" in context


def test_nothing_is_said_when_nothing_was_filtered():
    emma = _agent(at="Emma_home.Living_room")

    context = emma.build_decision_context(
        internal_state={"values": {}}, triggers=[], day_number=1,
        time_text="10:00 AM", current_location="Emma_home.Living_room",
    )

    assert "still exist" not in context


# --- 对账：谓词说不行，handler 就必须也说不行 -----------------------------------

# (工具名, 一组合法参数)。参数要合法，否则被拒是因为参数错，验不到位置。
PROBES = {
    "buy": {"thought": "t", "item": "cold_medicine"},
    "check_stock": {"thought": "t", "shop": "Pharmacy"},
    "restock": {"thought": "t", "item": "bread", "quantity": 1},
    "give_item": {"thought": "t", "recipient": "Mia Thompson", "item": "cake"},
    "sleep": {"thought": "t", "duration_minutes": 60},
}

PLACES = ["Emma_home.Living_room", "Park.Bench", "Pharmacy.Boss",
          "Supermarket.Counter", "Café_bar.Counter"]


@pytest.mark.parametrize("place", PLACES)
@pytest.mark.parametrize("name", sorted(PROBES))
def test_whatever_the_predicate_hides_the_handler_would_have_refused(name, place):
    """谓词过严 = 模型看不见一件其实能用的工具 = **丢能力**。

    所以反过来验：只要谓词说"现在用不了"，真 handler 就必须也拒绝。
    两边一旦走散，这个测试立刻红。
    """
    for cls in (EmmaHarris, RonParker, EllaParker):
        agent = _agent(cls, at=place)
        spec = tools.TOOL_REGISTRY[name]
        if not spec.is_eligible(agent.name):
            continue
        world = _world({agent.name: place, "Mia Thompson": place})

        why = spec.unavailable_reason(agent, world)
        if why is None:
            continue

        result = spec.handler(agent, dict(PROBES[name]), world)
        assert not result["ok"], (
            f"{agent.name} 在 {place}：谓词说 {name} 用不了（{why}），"
            f"但 handler 放行了——模型白白看不见一件能用的工具"
        )
