"""上下文层的契约：这一轮，居民该看见什么、不该看见什么。

这一层的规则都是**踩过坑才定下来的**，可它们此前只以注释的形式散在一个
110 行的方法里——改坏任何一条，测试都不会红。这个文件就是把它们钉住。

两类测试：

**契约**——每条规则一个测试，说清它为什么在。
**标尺**——三份重构前录下来的输出，一字不差。抽模块那次靠它证明
"我只是搬了个家"不是自称。往后它还兼职另一件事：**prompt 变了就会红**，
逼你确认那是有意的。

标尺过期了怎么办：确认改动是有意的之后，重跑
``python -m tests.regenerate_context_fixture``（见文件末尾的说明）。
"""

import json
import tempfile
from pathlib import Path

import pytest
from agents.agent import EmmaHarris
from memory.memory_system import MemorySystem
from memory.persona_store import persona_store
from runtime.context_builder import SECTIONS, ContextRequest, build

FIXTURE = Path(__file__).with_name("fixtures") / "decision_context.json"


@pytest.fixture
def agent(tmp_path, monkeypatch):
    """一个可复现的居民：空记忆库、空 persona。"""
    monkeypatch.setattr(persona_store, "persona_dir", tmp_path / "personas")
    memory = MemorySystem(retention_days=15, memory_dir=tmp_path / "memories")
    memory.initialize_agents(["Emma Harris"])
    return EmmaHarris(memory, "Emma_home.Living_room")


def _request(**overrides):
    base = dict(
        internal_state={"values": {"hunger": 40, "energy": 80, "social": 60}},
        triggers=[], day_number=1, time_text="10:00 AM",
        current_location="Emma_home.Living_room",
    )
    base.update(overrides)
    return ContextRequest(**base)


# --- 规则一：分界线是「这是关于谁的」 -------------------------------------------

def test_your_own_purse_and_bag_come_free(agent):
    """自己兜里有什么，不该花一个动作去数。

    曾经有个 ``check_balance`` 工具，三天被调 161 次（Emma 一人 43 次），
    而她的余额从头到尾没变过。删了，改成免费进上下文。
    """
    context = build(agent, _request(balance=7, holdings={"cake": 1, "milk": 0}))

    assert "7 in your purse" in context
    assert "cake x1" in context
    # 只看"你带着什么"那一行：milk 现在也出现在镇上的价目表里，
    # 扫全文就分不清"背包里有"和"店里有卖"了。
    carrying = next(line for line in context.splitlines() if "in your purse" in line)
    assert "milk" not in carrying, "数量为 0 的东西不该出现在背包里"


def test_letters_come_as_a_count_never_as_content(agent):
    """信的**内容**是别人的东西，要花一步 check_inbox 去取。

    全文自动塞进来，等于每次决策都为可能用不上的信付 token。
    """
    context = build(agent, _request(unread_letters=2))

    assert "2 unread letters" in context


def test_an_empty_mailbox_is_said_out_loud(agent):
    """真跑两天：``check_inbox`` 被调 49 次，其中 **48 次空手而归**——
    因为"没信就不提示"让模型只能盲查。省那点字换来四十八次完整调用。"""
    context = build(agent, _request(unread_letters=0))

    assert "mailbox is empty" in context


def test_you_only_see_people_in_the_same_area(agent):
    """世界知道所有人在哪，**居民不知道**。想知道远处谁在哪只能写信打听——
    这是通信之所以有存在意义的全部原因。"""
    alone = build(agent, _request())
    together = build(agent, _request(visible_agents=["Ella Parker"]))

    assert "cannot see anyone else" in alone
    assert "Ella Parker" in together
    # 名单之外的人一个字都不能漏出去
    assert "Mia Thompson" not in together


# --- 规则二：当下免费，未来要查 -------------------------------------------------

def test_the_weather_right_now_is_free_but_the_forecast_is_not(agent):
    """抬头看得见的免费，未来几小时要调 ``check_weather``。

    天气横跨这条线，是这条规则最干净的例子。
    """
    context = build(agent, _request(weather="light showers"))

    assert "weather right now: light showers" in context
    assert "forecast" not in context.lower(), "预报不该免费进来"


# --- 规则三：学到的和撞墙的要分开 ----------------------------------------------

def test_what_you_learned_and_what_refused_you_are_two_separate_blocks(agent):
    """混在一起时，"刚知道的事实"和"刚关上的门"长得一模一样，
    那句"别重复被拒的"就淹没在列表里。三天真跑里同轮重复提问 83 次。"""
    context = build(agent, _request(scratchpad=[
        {"tool": "check_inbox", "summary": "", "ok": True,
         "observation": "You read 1 letter: come to the cafe."},
        {"tool": "move_to", "summary": "destination='Pharmacy.Boss'", "ok": False,
         "observation": "Pharmacy is closed at 3:00 PM."},
    ]))

    learned_at = context.index("What you have found out this turn")
    refused_at = context.index("What the town refused this turn")
    assert learned_at < refused_at

    # 学到的**只给结果**——哪个工具查到的无关紧要
    learned_block = context[learned_at:refused_at]
    assert "come to the cafe" in learned_block
    assert "check_inbox(" not in learned_block

    # 被拒的**保留工具和参数**——要防的正是重复同一个调用
    refused_block = context[refused_at:]
    assert "move_to(destination='Pharmacy.Boss')" in refused_block


def test_nothing_about_this_turn_shows_up_before_the_first_step(agent):
    context = build(agent, _request())

    assert "found out this turn" not in context
    assert "refused this turn" not in context


# --- 被摘掉的工具仍然看得见 -----------------------------------------------------

def test_filtered_out_tools_are_named_and_marked_as_still_possible(agent):
    """摘的是 schema 的字数，不是能力。看不见的能力模型不会为它做计划。"""
    context = build(agent, _request(
        hidden_tools=[("buy", "you have to be standing inside a shop")]))

    assert "buy" in context
    assert "you have to be standing inside a shop" in context
    assert "still exist" in context


# --- 段本身 --------------------------------------------------------------------

def test_every_section_returns_a_string_even_with_nothing_to_say(agent):
    """任何一段返回 None 都会让 join 炸掉，而它只在某个字段恰好为空时发生。"""
    request = _request()

    for section in SECTIONS:
        assert isinstance(section(agent, request), str), section.__name__


def test_every_section_explains_why_it_exists():
    """这一层的每条规则都是踩坑换来的。没有 docstring 的段，
    等于把理由丢了——下一个人只会看到一串字符串拼接。"""
    undocumented = [s.__name__ for s in SECTIONS if not (s.__doc__ or "").strip()]
    assert undocumented == ["closing"], f"这些段没写为什么：{undocumented}"


def test_the_turn_so_far_comes_last_before_the_instruction(agent):
    """靠前的是底子（你是谁、在哪、有什么），靠后的是这一轮试过什么——
    最靠近要做的那个决定。顺序别随手调。"""
    names = [s.__name__ for s in SECTIONS]

    assert names[0] == "opening"
    assert names[-1] == "closing"
    assert names.index("what_you_tried_this_turn") == len(names) - 2


# --- 标尺：重构不许改变输出 -----------------------------------------------------

def test_the_context_still_reads_exactly_as_it_did_before_the_refactor(tmp_path, monkeypatch):
    """三份在抽模块**之前**录下来的输出。

    ⚠️ 这个测试红了不一定是坏事——它也可能是你**有意**改了 prompt。
    确认之后重新录制标尺即可（见文件开头）。它的作用是让 prompt 的改动
    没法悄悄发生。
    """
    monkeypatch.setattr(persona_store, "persona_dir", tmp_path / "personas")
    memory = MemorySystem(retention_days=15, memory_dir=tmp_path / "memories")
    memory.initialize_agents(["Emma Harris"])

    golden = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert golden, "标尺文件是空的"

    for name, case in golden.items():
        subject = EmmaHarris(memory, "Emma_home.Living_room")
        if name == "mid_turn":
            subject.last_observation = "Nobody else is here."
        assert subject.build_decision_context(**case["kwargs"]) == case["expected"], name


# --- 价格：给事实，不给结论 ------------------------------------------------------

def test_prices_come_free(agent):
    """单步用例抓到的：Emma 站在药房、兜里 3 块、任务是买药，三次都点了 buy。

    **她不是不会比大小，是不知道药要 8 块**——余额在上下文里，价格不在。
    """
    context = build(agent, _request(balance=3))

    assert "3 in your purse" in context
    assert "cold_medicine 8" in context


def test_the_whole_price_list_is_there_not_only_what_a_task_named(agent):
    """**住在这儿的人知道一杯咖啡多少钱。**

    曾经只给"任务点名的那几样"，理由是整张表九成时间是噪声。放弃那条是因为
    它把**知道价格**变成了**接过任务**的副产品：Arthur 开局就拿着蛋糕、直接
    约见面、从没调过 ``accept_task``，于是他连蛋糕多少钱都看不到。
    """
    context = build(agent, _request())

    for item in ("cold_medicine", "coffee", "bread", "vitamins", "cake"):
        assert item in context, f"{item} 的价格也该是常识"


def test_it_gives_the_fact_not_the_verdict(agent):
    """只说多少钱，不说"你买不起"。

    余额、天气、看得见的人，给的都是**事实**。替它把差额算好，省下的是它
    本来就会的一步，换来的是再也测不出它会不会算。
    """
    context = build(agent, _request(balance=3))

    for verdict in ("short", "cannot afford", "not enough", "afford"):
        assert verdict not in context.lower()


def test_prices_do_not_depend_on_having_a_task(agent):
    """没有任务也看得到价格——否则"知道多少钱"就成了"接过差事"的副产品。"""
    assert "What things cost" in build(agent, _request())


# --- 按段名消融 ------------------------------------------------------------------

def test_a_section_can_be_switched_off_by_name(agent):
    """消融靠它：关掉某一段再跑同一张记分卡，看达成率掉不掉。

    做成按段名关、而不是每做一个实验加一个布尔开关——这样**每一段都自动
    成了可测的一维**。
    """
    on = build(agent, _request())
    off = build(agent, _request(omit=frozenset({"what_things_cost"})))

    assert "What things cost" in on
    assert "What things cost" not in off
    assert len(off) < len(on)


def test_every_ablatable_section_name_really_exists():
    """打错一个段名，消融就静默失效——关掉一个不存在的段等于什么都没关，
    而消融组会跑出和基线一模一样的数字，看上去像"这段没用"。"""
    from evals.ablations import ABLATION_REGISTRY
    from runtime.context_builder import SECTION_NAMES

    for name, ablation in ABLATION_REGISTRY.items():
        unknown = set(ablation.omit_context) - SECTION_NAMES
        assert not unknown, f"消融 {name} 想关掉不存在的段 {sorted(unknown)}"


# --- 「自从上次以来发生了什么」---------------------------------------------------

def test_things_that_happened_are_told_in_the_second_person(agent):
    """上下文里唯一一段说"发生过"的，其余全是"现在是什么状态"。

    转账对收款人本来完全无声：Emma 借到的 5 块到账时她那边一个字都没有，
    只有余额从 3 变成 8。
    """
    from world.events import EventLog, MONEY_SENT

    log = EventLog()
    log.record(MONEY_SENT, "Gavin Harris", visible_to={"Emma Harris"},
               amount=5, recipient="Emma Harris")

    context = build(agent, _request(recent_events=tuple(log.take_new("Emma Harris"))))

    assert "Since you last acted:" in context
    assert "Gavin Harris sent you 5." in context


def test_nothing_is_said_when_nothing_happened(agent):
    assert "Since you last acted" not in build(agent, _request())


# --- 住在这儿的人本来就知道的 -------------------------------------------------------
#
# 这一段补的是**失忆，不是信息不对称**。世界一直知道药房六点关门，居民却只在
# 撞上关门之后才被告知——整轮评估 `closed` 撞了 377 次，占全部驳回的 15%。

def test_you_know_when_the_shops_open(agent):
    context = build(agent, _request())

    assert "Pharmacy 9:00 AM–6:00 PM" in context
    assert "Supermarket 8:00 AM–9:00 PM" in context
    assert "Café bar 7:00 AM–10:00 PM" in context


def test_you_know_how_many_fit_and_who_keeps_which_shop(agent):
    context = build(agent, _request())

    assert "room for 3 customers" in context
    assert "Ella Parker keeps the Pharmacy" in context
    assert "Ron Parker keeps the Supermarket" in context
    assert "no keeper" in context, "咖啡馆无人经营，问不到人，这一点得说明"


def test_you_know_the_rules_you_could_not_have_worked_out(agent):
    """镇上没有当面要钱这件事，也没有隔空递东西这件事。**模型无从推断**，
    以前只能靠撞墙学。"""
    context = build(agent, _request()).lower()

    assert "same place" in context, "当面才交得了东西"
    assert "sent to anyone from anywhere" in context, "钱可以隔空转"


def test_what_changes_is_still_not_given_away(agent):
    """⚠️ 关键在**会不会变**。营业时间是常识，库存不是——把库存也塞进来
    就等于白送一份实时账本，check_stock 和写信打听就都没意义了。"""
    context = build(agent, _request())

    for leak in ("on the shelf", "in stock", "still has", "remaining"):
        assert leak not in context.lower()


def test_town_knowledge_can_be_ablated_on_its_own(agent):
    """要证明这 200 个 token 值不值，得能单独把它关掉。"""
    on = build(agent, _request())
    off = build(agent, _request(omit=frozenset({"what_this_town_is_like"})))

    assert "9:00 AM–6:00 PM" in on
    assert "9:00 AM–6:00 PM" not in off
    assert "What things cost" in off, "关掉常识不该顺带关掉价目表"
