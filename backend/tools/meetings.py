"""答应和某人在某时某地见面。

两轮真跑加起来 141 次"对方不在场"。Emma 交付一盒药撞了三次、花了十二个
小时、两次都超时——不是因为买不到药，而是因为**见面这件事只能靠偶遇**：
她不知道 Adam 在哪，Adam 不知道她在找自己，两个人在镇上各走各的，撞上纯
属运气。

约定把偶遇变成安排。

## 为什么提议用写信、接受用工具

提议的内容（几点、在哪、为了什么）用自然语言写最省事，专门做个
``propose_meeting`` 只是给同一件事多加一层 schema。但**接受必须是结构化
的**，否则判定无从下手——"好啊，那就下午吧"没法拿去和世界状态比对。

于是分工变成：写信提议，读信的人把信里的意思**翻译成结构化的调用**。这
恰恰是 LLM 该做的事，也是这套系统里最能体现 agent 能力的一步。

## 接受即生效，不必再回一封确认信

一次 ``accept_meeting`` 给双方各建一个 goal。提议的那一方下一轮就会在自己
的上下文里看到这个约定——接受的动作直接改变了双方的世界状态。少一封确认
信，就少一轮几小时的延迟；而这个世界里，延迟正是任务失败的主因。
"""

from tools.base import THOUGHT_FIELD, accept, reject
from world.locations import AGENT_NAMES, MEETING_AREAS

ACCEPT_MEETING_PARAMETERS = {
    "type": "object",
    "properties": {
        "thought": THOUGHT_FIELD,
        "with_person": {
            "type": "string",
            "enum": AGENT_NAMES,
            "description": "Who you are arranging to meet.",
        },
        "where": {
            "type": "string",
            "enum": MEETING_AREAS,
            "description": (
                "Which part of town. Anywhere in that area counts as meeting — "
                "you do not have to be on the same bench."
            ),
        },
        "at_hour": {
            "type": "integer",
            "minimum": 1,
            "maximum": 23,
            "description": "The hour of today you will both be there, 24-hour clock.",
        },
        "reason": {
            "type": "string",
            "description": "One short line on what the meeting is for.",
        },
    },
    "required": ["thought", "with_person", "where", "at_hour", "reason"],
}


def handle_accept_meeting(agent, args, world=None):
    """和另一位居民定下时间地点。

    双方各得到一条记录，共享同一个时间与地点，并从此免费出现在两个人的
    决策上下文里。快到点时上下文顶部会单独顶出一行提醒——三天的数据显示
    模型连上一步查过的余额都记不住，三小时前的约定更不可能自己想起来。

    履约判定要求**两个人都在**那个区域。只查自己的话，一个人在空荡荡的
    公园干等也会被算作赴约成功，那这个指标就没有意义了。
    """
    from world.goals import goal_store
    from world.snapshot import EMPTY_WORLD, format_clock

    world = world or EMPTY_WORLD
    other = (args or {}).get("with_person")
    if other not in AGENT_NAMES:
        return reject("unknown_person", f"There is nobody called {other!r} in Valentown.")
    if other == agent.name:
        return reject("self_meeting", "You cannot arrange to meet yourself.")

    area = (args or {}).get("where")
    if area not in MEETING_AREAS:
        return reject("unknown_place", f"There is no part of town called {area!r}.")

    try:
        hour = int((args or {}).get("at_hour"))
    except (TypeError, ValueError):
        return reject("bad_time", "You did not say when.")
    at_minute = max(0, min(23, hour)) * 60
    if at_minute <= world.time_minutes:
        return reject(
            "time_passed",
            f"It is already {world.time_text}, so {hour}:00 today has gone by. "
            f"Pick a later hour.",
        )

    result = goal_store.arrange_meeting(
        first=agent.name, second=other, area=area, at_minute=at_minute,
        life_day=world.life_day, reason=(args or {}).get("reason") or "",
    )
    if not result["ok"]:
        if result["reason"] == "already_taken":
            return reject("already_taken", "That arrangement already stands.")
        if result["reason"] == "too_many":
            return reject(
                "too_many",
                f"One of you already has as many arrangements as you can keep. "
                f"Nothing was agreed.",
            )
        return reject("cannot_arrange", "That arrangement could not be made.")

    return accept(
        f"Agreed: you and {other} will be at {area} at {format_clock(at_minute)}. "
        f"It is now on both your plans, and you will be reminded as the time nears.",
        meeting=result["description"],
    )
