"""工具注册表：Agent 可以调用的每一件事。

包的结构对应工具的分类：

    base.py            ToolSpec、执行结果构造、共用参数片段
    movement.py        move_to · stay · sleep    占用游戏时间，会收敛本轮
    communication.py   send_mail · check_inbox   改变世界但不占时间
    shopping.py        check_stock · buy · restock   同上
    wallet.py          transfer · give_item      同上
    tasks.py           accept_task               记下跨轮才做得完的事
    meetings.py        accept_meeting            和人约时间地点
    weather.py         check_weather             纯查询
    remembering.py     recall                    纯查询

**工具是门，世界服务是房间。**数据和原子操作全在 ``world/`` 包里
（``economy`` · ``mailbox`` · ``goals`` · ``weather`` · ``locations``），
这里的 handler 只负责判断"你有没有资格进"，以及把结果翻译成模型看得懂
的一句话。依赖方向是单向的：``tools`` 依赖 ``world``，``world`` 不认识
``tools``。

决策循环不需要认识任何具体工具，只需要问一句
``if spec.terminal and result["ok"]: break``。往注册表里加新工具时——
新增一个模块、在下面登记一条——``runtime/`` 一行都不用改。
"""

from world.economy import SHOP_OWNERS
from tools.base import (  # noqa: F401  （re-export，调用方无需知道内部分层）
    THOUGHT_FIELD,
    ToolSpec,
    accept,
    reject,
)
from tools.communication import (
    CHECK_INBOX_PARAMETERS,
    SEND_MAIL_PARAMETERS,
    handle_check_inbox,
    handle_send_mail,
)
from world.locations import (  # noqa: F401  （re-export）
    AGENT_NAMES,
    ALLOWED_DESTINATIONS,
    DEFAULT_ACTION_MINUTES,
    HOME_AREAS,
    HOME_ROOM_LOCATIONS,
    MAX_ACTION_MINUTES,
    MIN_ACTION_MINUTES,
    PUBLIC_LOCATIONS,
    build_allowed_destinations,
)
from tools.movement import (
    MOVE_TO_PARAMETERS,
    sleep_available,
    SLEEP_PARAMETERS,
    STAY_PARAMETERS,
    handle_move_to,
    handle_sleep,
    handle_stay,
)
from tools.remembering import RECALL_PARAMETERS, handle_recall
from tools.meetings import ACCEPT_MEETING_PARAMETERS, handle_accept_meeting
from tools.tasks import ACCEPT_TASK_PARAMETERS, handle_accept_task
from tools.weather import CHECK_WEATHER_PARAMETERS, handle_check_weather
from tools.wallet import (
    GIVE_ITEM_PARAMETERS,
    give_item_available,
    TRANSFER_PARAMETERS,
    handle_give_item,
    handle_transfer,
)
from tools.shopping import (
    BUY_PARAMETERS,
    buy_available,
    check_stock_available,
    restock_available,
    CHECK_STOCK_PARAMETERS,
    RESTOCK_PARAMETERS,
    handle_buy,
    handle_check_stock,
    handle_restock,
)



TOOL_REGISTRY = {
    "move_to": ToolSpec(
        name="move_to",
        description="Walk somewhere and spend time doing something there. This ends your turn.",
        parameters=MOVE_TO_PARAMETERS,
        handler=handle_move_to,
        terminal=True,
    ),
    "stay": ToolSpec(
        name="stay",
        description=(
            "Keep doing something where you already are, without going anywhere. "
            "Use this to carry on with an activity, or simply to wait for someone "
            "or something. This ends your turn."
        ),
        parameters=STAY_PARAMETERS,
        handler=handle_stay,
        terminal=True,
    ),
    "sleep": ToolSpec(
        name="sleep",
        description=(
            "Go to sleep at home. Unlike anything else you can do, this can run "
            "right through the night — say how many minutes. This ends your turn."
        ),
        parameters=SLEEP_PARAMETERS,
        handler=handle_sleep,
        terminal=True,
        available_now=sleep_available,
    ),
    "send_mail": ToolSpec(
        name="send_mail",
        description=(
            "Write a short letter to another resident. Costs no time and does not "
            "end your turn. They will only read it the next time they check their "
            "mailbox, so do not expect an immediate reply."
        ),
        parameters=SEND_MAIL_PARAMETERS,
        handler=handle_send_mail,
        terminal=False,
        max_per_turn=1,
    ),
    "check_inbox": ToolSpec(
        name="check_inbox",
        description=(
            "Read the letters other residents have sent you. Costs no time and "
            "does not end your turn."
        ),
        parameters=CHECK_INBOX_PARAMETERS,
        handler=handle_check_inbox,
        terminal=False,
        read_only=True,
        max_per_turn=1,
    ),
    "check_stock": ToolSpec(
        name="check_stock",
        description=(
            "See what a shop has on its shelves and what it costs. You must be "
            "inside the shop, unless you own it. Costs no time and does not end "
            "your turn."
        ),
        parameters=CHECK_STOCK_PARAMETERS,
        handler=handle_check_stock,
        terminal=False,
        read_only=True,
        max_per_turn=2,
        available_now=check_stock_available,
    ),
    "buy": ToolSpec(
        name="buy",
        description=(
            "Buy one item from the shop you are standing in. Costs no time and "
            "does not end your turn."
        ),
        parameters=BUY_PARAMETERS,
        handler=handle_buy,
        terminal=False,
        max_per_turn=2,
        available_now=buy_available,
    ),
    "restock": ToolSpec(
        name="restock",
        description=(
            "Order stock in for the shop you own, paying for it yourself. Only "
            "works in your own shop. Costs no time and does not end your turn."
        ),
        parameters=RESTOCK_PARAMETERS,
        handler=handle_restock,
        terminal=False,
        max_per_turn=3,
        available_now=restock_available,
        # 店主身份是永久的，其余五个人一辈子也补不了货——两天真跑里，
        # 这件工具在他们身上白烧了七万多 token。
        eligible=lambda name: name in set(SHOP_OWNERS.values()),
    ),
    "transfer": ToolSpec(
        name="transfer",
        description=(
            "Send money to another resident. Instant, and it does not end your turn. "
            "This cannot be undone, so be sure before you send."
        ),
        parameters=TRANSFER_PARAMETERS,
        handler=handle_transfer,
        terminal=False,
        max_per_turn=1,
    ),
    "give_item": ToolSpec(
        name="give_item",
        description=(
            "Hand something you are carrying to another resident. They have to be "
            "here with you — unlike money, things cannot be sent from a distance. "
            "Costs no time and does not end your turn."
        ),
        parameters=GIVE_ITEM_PARAMETERS,
        handler=handle_give_item,
        terminal=False,
        max_per_turn=2,
        available_now=give_item_available,
    ),
    "check_weather": ToolSpec(
        name="check_weather",
        description=(
            "Look at the forecast for the next few hours. You can already see what "
            "the weather is doing right now; this tells you what is coming. Costs "
            "no time and does not end your turn."
        ),
        parameters=CHECK_WEATHER_PARAMETERS,
        handler=handle_check_weather,
        terminal=False,
        read_only=True,
        max_per_turn=1,
    ),
    "accept_task": ToolSpec(
        name="accept_task",
        description=(
            "Commit to getting something into someone's hands by a certain hour "
            "today — yours or another resident's. It stays in front of you every "
            "turn until it is done or the time runs out. Use it whenever a job "
            "will take more than one move. Costs no time and does not end your turn."
        ),
        parameters=ACCEPT_TASK_PARAMETERS,
        handler=handle_accept_task,
        terminal=False,
        max_per_turn=1,
    ),
    "accept_meeting": ToolSpec(
        name="accept_meeting",
        description=(
            "Agree with another resident to be in the same part of town at a "
            "certain hour today. Use it when a letter proposes meeting up, or "
            "when you need to hand something over — wandering about hoping to "
            "run into someone rarely works. It goes on both your plans. Costs "
            "no time and does not end your turn."
        ),
        parameters=ACCEPT_MEETING_PARAMETERS,
        handler=handle_accept_meeting,
        terminal=False,
        max_per_turn=1,
    ),
    "recall": ToolSpec(
        name="recall",
        description=(
            "Search your own memories for something specific. "
            "Costs no time and does not end your turn — use it before deciding "
            "when past events matter."
        ),
        parameters=RECALL_PARAMETERS,
        handler=handle_recall,
        terminal=False,
        read_only=True,
        max_per_turn=3,
    ),
}


def get_tool(name):
    """按名字取工具；模型给出未知名字时返回 None 由调用方拒绝。"""
    return TOOL_REGISTRY.get(name)


def function_schemas(agent_name=None):
    """这位居民看得见的工具声明，可直接作为 API 的 tools 参数。

    只按**永久**资格过滤（店主才有的 ``restock``）。此刻用不了的能力
    仍然摆在台面上——看不见的能力，模型不会为它做计划。
    """
    return [
        spec.to_function_schema(agent_name)
        for spec in TOOL_REGISTRY.values()
        if spec.is_eligible(agent_name)
    ]


def schemas_for_now(agent, world):
    """按**此刻**再筛一道，返回 ``(schemas, hidden)``。

    ``hidden`` 是 ``[(工具名, 为什么现在用不了), ...]``——调用方要把它写进
    决策上下文。**摘掉的是 schema，不是能力**：一行「buy（要先进店）」
    约 11 tokens，而 buy 的完整 schema 是 156。

    起因是量出来的：输入的 85% 是工具 schema，而且每次一模一样。

    ⚠️ 这里走 ``function_schemas``（模块内的名字，调用时才解析）而不是直接
    遍历注册表——消融实验靠替换那个名字来摘工具，绕过去的话「摘掉的工具」
    会从这条路重新冒出来。

    ⚠️ ``move_to`` / ``stay`` 没有谓词，所以本轮**至少还剩一个收敛点**。
    真把它们摘光了，这一轮无论如何都做不出动作——``test_tool_filter.py``
    钉死了这条。
    """
    keep, hidden = [], []
    for schema in function_schemas(agent.name):
        name = schema["function"]["name"]
        spec = TOOL_REGISTRY.get(name)
        why = spec.unavailable_reason(agent, world) if spec else None
        if why:
            hidden.append((name, why))
        else:
            keep.append(schema)
    return keep, hidden
