"""评估层的测试：场景埋对没有、判据判得准不准。不跑一次 LLM。

判据是整个评估集的地基——它说了算。它要是判错了，后面所有数字都是
装饰。所以这里正反两面都测：**埋完之后必须是没做到**，
**把世界摆成做到的样子必须判成做到**。

第一条尤其要紧：一道题如果一开始判据就成立，早停会在第一批决策后立刻
触发，那一格**什么都没测到却显示满分**。这不会报错，只会让记分卡说谎。
"""

import pytest

from evals.ablations import ABLATION_REGISTRY
from evals.scenarios import SCENARIO_REGISTRY
from llm import LLMClient
from runtime.scheduler import Town

SEEDED = [name for name in sorted(SCENARIO_REGISTRY) if name != "natural"]


@pytest.fixture(autouse=True)
def no_real_llm(monkeypatch):
    monkeypatch.setattr(LLMClient, "call_tools", lambda self, *a, **k: None)
    monkeypatch.setattr(LLMClient, "get_response", lambda self, *a, **k: None)
    monkeypatch.setattr(LLMClient, "rate_importance",
                        lambda self, name, text, fallback=4: fallback)


# --- 埋点 --------------------------------------------------------------------

@pytest.mark.parametrize("name", SEEDED)
def test_a_freshly_seeded_scenario_is_not_already_solved(name):
    """埋完就成立的话，早停会在第一批决策后触发，那一格什么都没测到
    却显示满分。这不会报错，只会让记分卡说谎。"""
    scenario = SCENARIO_REGISTRY[name]
    with Town(days=1) as town:
        scenario.seed(town)
        assert scenario.judge(town)["passed"] is False, f"{name} 一开局就算过了"


def test_the_control_group_has_no_verdict_at_all():
    """``natural`` 是控制组，没有判据——它绝不能触发早停。"""
    scenario = SCENARIO_REGISTRY["natural"]
    with Town(days=1) as town:
        scenario.seed(town)
        assert scenario.judge(town)["passed"] is None
        assert bool(scenario.judge(town)["passed"]) is False   # runner 就是这么用的


def test_errand_leaves_emma_short_of_the_price():
    """差多少钱是这道题的全部难度所在。差得不够就不用开口借钱了。"""
    from world.economy import CATALOG

    scenario = SCENARIO_REGISTRY["errand"]
    with Town(days=1) as town:
        scenario.seed(town)
        price = CATALOG["Pharmacy"]["items"]["cold_medicine"]
        assert town.economy.balance("Emma Harris") < price
        assert town.mailbox.unread_counts().get("Emma Harris") == 1


def test_rendezvous_puts_the_cake_in_arthurs_hands_not_mias():
    scenario = SCENARIO_REGISTRY["rendezvous"]
    with Town(days=1) as town:
        scenario.seed(town)
        assert town.economy.holdings("Arthur Morgan").get("cake") == 1
        assert town.economy.holdings("Mia Thompson").get("cake", 0) == 0


def test_scarcity_really_leaves_only_one_on_the_shelf():
    scenario = SCENARIO_REGISTRY["scarcity"]
    with Town(days=1) as town:
        scenario.seed(town)
        assert town.economy.count("Pharmacy", "cold_medicine") == 1
        # 两个人都买得起，否则考的就成了"谁有钱"而不是"谁抢到"
        for who in ("Emma Harris", "Mia Thompson"):
            assert town.economy.balance(who) >= 8


# --- 判据 --------------------------------------------------------------------

def test_errand_passes_only_when_the_medicine_is_actually_in_adams_hands():
    scenario = SCENARIO_REGISTRY["errand"]
    with Town(days=1) as town:
        scenario.seed(town)

        # 药在 Emma 手上还不算——这道题的终点是**当面交到 Adam 手上**。
        town.economy.seed(holdings={"Emma Harris": {"cold_medicine": 1}})
        assert scenario.judge(town)["passed"] is False

        town.economy.seed(holdings={"Adam Harris": {"cold_medicine": 1}})
        assert scenario.judge(town)["passed"] is True


def test_rendezvous_passes_only_when_the_cake_has_changed_hands():
    scenario = SCENARIO_REGISTRY["rendezvous"]
    with Town(days=1) as town:
        scenario.seed(town)
        assert scenario.judge(town)["passed"] is False

        town.economy.seed(holdings={"Mia Thompson": {"cake": 1}})
        assert scenario.judge(town)["passed"] is True


def test_scarcity_fails_when_the_shop_oversells():
    """两个人都拿到 = 超卖。那比谁都没买到严重得多——那是世界写错了。"""
    scenario = SCENARIO_REGISTRY["scarcity"]
    with Town(days=1) as town:
        scenario.seed(town)

        town.economy.seed(holdings={"Emma Harris": {"cold_medicine": 1}})
        assert scenario.judge(town)["passed"] is True

        town.economy.seed(holdings={"Mia Thompson": {"cold_medicine": 1}})
        verdict = scenario.judge(town)
        assert verdict["passed"] is False
        assert "超卖" in verdict["detail"]


# --- 注册表 ------------------------------------------------------------------

def test_every_ablation_actually_takes_something_away():
    """``none`` 之外的每一项都必须真的关掉点什么，否则它和基线跑出
    一样的数字，看上去像"这个能力没用"。"""
    for name, ablation in ABLATION_REGISTRY.items():
        # ⚠️ 加了新旋钮就要加到这里来。漏登记的话，一条"什么都没关掉"的
        # 消融会安静地和基线跑出同样的数字，被读成"这个能力没用"。
        # 注意 handover_windows 的"开"是 True，所以取反才算一个旋钮。
        knobs = (ablation.tools_disabled, ablation.max_steps,
                 ablation.filter_tools, ablation.omit_context,
                 not ablation.handover_windows)
        if name == "none":
            assert not any(knobs), "基线不该关掉任何东西"
        else:
            assert any(knobs), f"{name} 什么都没关，会和基线跑出一样的数字"


def test_every_ablated_tool_name_really_exists():
    """打错一个工具名，消融就会静默失效——摘掉一个不存在的工具等于没摘。"""
    from tools import TOOL_REGISTRY

    for name, ablation in ABLATION_REGISTRY.items():
        unknown = set(ablation.tools_disabled) - set(TOOL_REGISTRY)
        assert not unknown, f"消融 {name} 想摘掉不存在的工具 {sorted(unknown)}"


def test_every_scenario_declares_a_decision_budget():
    for name, scenario in SCENARIO_REGISTRY.items():
        assert scenario.max_decisions > 0, f"{name} 没有决策上限，会一直跑下去"
        assert scenario.days >= 1


# --- pre-rebuild：真正的改造前 -------------------------------------------------

def test_pre_rebuild_leaves_exactly_one_tool_and_one_step():
    """改造前是"只有 move_to + 强制调用 + 单步"。

    单工具 + `tool_choice: required` 等价于当年那句
    `tool_choice: {"name": "move_to"}` —— 模型没得选，只能产出一个动作。
    """
    from tools import TOOL_REGISTRY

    ablation = ABLATION_REGISTRY["pre-rebuild"]

    assert ablation.max_steps == 1
    assert set(ablation.tools_disabled) == set(TOOL_REGISTRY) - {"move_to"}


def test_pre_rebuild_really_leaves_only_move_to_at_runtime():
    import tools

    with Town(days=1, tools_disabled=ABLATION_REGISTRY["pre-rebuild"].tools_disabled):
        names = [schema["function"]["name"]
                 for schema in tools.function_schemas("Ron Parker")]
        assert names == ["move_to"]


def test_single_step_is_not_the_same_thing_as_pre_rebuild():
    """把 `single-step` 当成"改造前"是稻草人：它给了工具选择权却不给
    第二步，所以模型一旦挑了查询类工具，这一轮就作废——比改造前更差，
    而差的那部分不是改造带来的。"""
    single = ABLATION_REGISTRY["single-step"]
    pre = ABLATION_REGISTRY["pre-rebuild"]

    assert single.max_steps == pre.max_steps == 1
    assert not single.tools_disabled          # 工具一件没摘
    assert pre.tools_disabled                 # 只剩 move_to


# --- 分段判据 -----------------------------------------------------------------

@pytest.mark.parametrize("name", SEEDED)
def test_a_freshly_seeded_scenario_has_not_reached_any_stage(name):
    scenario = SCENARIO_REGISTRY[name]
    with Town(days=1) as town:
        scenario.seed(town)
        reached = [s.name for s in scenario.stages if s.reached(town)]
        assert reached == [], f"{name} 一开局就走到了 {reached}"


@pytest.mark.parametrize("name", SEEDED)
def test_stage_names_are_unique(name):
    """重名的环会被高水位那个 set 吞掉一个，进度就永远差一。"""
    names = [s.name for s in SCENARIO_REGISTRY[name].stages]
    assert len(names) == len(set(names))


def test_a_middle_stage_stops_being_true_which_is_why_we_track_a_high_water_mark():
    """**这就是分段必须边跑边查的原因。**

    "药买到手了"在交付之后就不成立了——药已经不在 Emma 手上。只在最后查
    一次的话，这一环会显示没走到，而它明明走过。
    """
    scenario = SCENARIO_REGISTRY["errand"]
    bought = next(s for s in scenario.stages if s.name == "买到药")

    with Town(days=1) as town:
        scenario.seed(town)
        town.economy.seed(holdings={"Emma Harris": {"cold_medicine": 1}})
        assert bought.reached(town) is True

        # 交付：药从 Emma 手上转到 Adam 手上
        town.economy.seed(holdings={"Emma Harris": {}, "Adam Harris": {"cold_medicine": 1}})
        assert bought.reached(town) is False, "这一环本来就是转瞬即逝的"
        assert scenario.judge(town)["passed"] is True


@pytest.mark.parametrize("name", ["errand", "rendezvous"])
def test_the_last_stage_and_the_verdict_agree(name):
    """最后一环就是目标本身。两边说的不是一回事，记分卡就自相矛盾了。"""
    scenario = SCENARIO_REGISTRY[name]
    goal_reached = {
        "errand": {"Adam Harris": {"cold_medicine": 1}},
        "rendezvous": {"Mia Thompson": {"cake": 1}},
    }[name]

    with Town(days=1) as town:
        scenario.seed(town)
        last = scenario.stages[-1]
        assert last.reached(town) is False
        assert scenario.judge(town)["passed"] is False

        town.economy.seed(holdings=goal_reached)
        assert last.reached(town) is True
        assert scenario.judge(town)["passed"] is True


# ---------- no-handover-window：消融必须真的关掉那几行 ----------
#
# ⚠️ **一条什么都没关掉的消融比没有消融更糟**：记分卡上它和基线一样，
# 读表的人会得出"这个能力没用"，而真相是它根本没被摘掉。

def test_the_handover_window_ablation_actually_silences_it():
    from evals.ablations import ABLATION_REGISTRY
    from runtime.scheduler import Town
    from world import goals
    from world.snapshot import snapshot

    def cake_in_hand_at_the_park(town):
        town.economy.seed(holdings={"Arthur Morgan": {"cake": 1}})
        town.goals.arrange_meeting("Arthur Morgan", "Mia Thompson", "Park",
                                   at_minute=15 * 60, life_day=1, reason="she asked")
        return snapshot(time_minutes=15 * 60, life_day=1,
                        agent_locations={"Arthur Morgan": "Park.Bench",
                                         "Mia Thompson": "Park.Tree"})

    with Town(days=1) as town:
        assert "right now" in goals.goal_store.summary_for(
            "Arthur Morgan", cake_in_hand_at_the_park(town)), "基线该看得见"

    off = ABLATION_REGISTRY["no-handover-window"]
    with Town(days=1, handover_windows=off.handover_windows) as town:
        assert "right now" not in goals.goal_store.summary_for(
            "Arthur Morgan", cake_in_hand_at_the_park(town)), "消融该看不见"


def test_the_ablation_leaves_the_tool_itself_alone():
    """摘的是**三行字**，不是一件工具。`give_item` 照样在，照样能调——
    否则量的就成了"没有这件工具做不成事"，那是另一个问题。"""
    from evals.ablations import ABLATION_REGISTRY

    off = ABLATION_REGISTRY["no-handover-window"]

    assert off.tools_disabled == ()
    assert off.omit_context == ()
    assert off.max_steps is None


def test_switching_it_off_is_restored_afterwards():
    """漏还原一处，同一进程里后面几十格全跟着关。"""
    from runtime.scheduler import Town
    from world import goals

    with Town(days=1, handover_windows=False):
        assert goals.HANDOVER_WINDOWS is False

    assert goals.HANDOVER_WINDOWS is True


def test_every_ablated_section_name_really_exists():
    """⚠️ 段名是**字符串**，打错一个字不会报错——它只是什么都没关掉，
    然后和基线跑出一样的数字，被读成"这段 context 没用"。

    和 ``_everything_except`` 从真注册表里减工具是同一个道理：
    **别让手写的名字和代码走散。**
    """
    from runtime.context_builder import SECTION_NAMES

    for name, ablation in ABLATION_REGISTRY.items():
        unknown = set(ablation.omit_context) - SECTION_NAMES
        assert not unknown, f"{name} 想关的段不存在：{sorted(unknown)}"
