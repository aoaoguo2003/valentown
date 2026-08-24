"""接下一件要做的事。

真跑两天的数据显示：**没有目标，居民就只能瞎逛**——有好几轮把五步全花在
查东西上，一个动作都没做出来。需求（饿、累）自己会响也一轮就能满足，
任务不会：它跨好几轮，而每轮的上下文都是重新组装的，scratchpad 一收敛就扔。

所以要有个地方替它记着，并且**免费**摆进每一轮的上下文。

判定由世界状态说了算，不是模型说了算——它说"我做完了"没有任何可信度。
"""

from tools.base import THOUGHT_FIELD, accept, reject
from tools.locations import AGENT_NAMES

ACCEPT_TASK_PARAMETERS = {
    "type": "object",
    "properties": {
        "thought": THOUGHT_FIELD,
        "item": {
            "type": "string",
            "description": (
                "What has to end up in someone's hands, e.g. 'cold_medicine'. "
                "It must be something a shop in Valentown sells."
            ),
        },
        "for_person": {
            "type": "string",
            "enum": AGENT_NAMES,
            "description": "Who should end up holding it. Can be yourself.",
        },
        "by_hour": {
            "type": "integer",
            "minimum": 1,
            "maximum": 23,
            "description": "The hour of today by which it should be done, 24-hour clock.",
        },
        "reason": {
            "type": "string",
            "description": "One short line on why, so you remember later what this was about.",
        },
    },
    "required": ["thought", "item", "for_person", "by_hour", "reason"],
}


def handle_accept_task(agent, args, world=None):
    """记下一件跨越好几轮才能做完的事。

    只支持一种形状：**让某样东西落到某人手上**。它足以支撑"帮人跑腿"这类
    任务的完整链条——查货、凑钱、买下、送到——而且判定干净利落：
    ``economy.holdings(那个人)[那样东西] > 0``。

    刻意不做"提醒自己去散步"这种没有客观终点的任务：判不出完成与否的目标
    对评估毫无价值，只会把上下文塞满。
    """
    from economy import ALL_ITEMS
    from goals import DELIVER, goal_store
    from world import EMPTY_WORLD

    world = world or EMPTY_WORLD
    item = str((args or {}).get("item") or "").strip()
    if item not in ALL_ITEMS:
        return reject(
            "unknown_item",
            f"Nothing called {item!r} is sold in Valentown, so that is not "
            f"something you could actually get hold of.",
        )

    person = (args or {}).get("for_person")
    if person not in AGENT_NAMES:
        return reject("unknown_person", f"There is nobody called {person!r} in Valentown.")

    try:
        hour = int((args or {}).get("by_hour"))
    except (TypeError, ValueError):
        return reject("bad_deadline", "You did not say by when.")
    deadline = max(0, min(23, hour)) * 60
    if deadline <= world.time_minutes:
        return reject(
            "deadline_passed",
            f"It is already {world.time_text}; a deadline of {hour}:00 today has gone by.",
        )

    result = goal_store.accept(
        owner=agent.name, kind=DELIVER, person=person, what=item,
        deadline_minute=deadline, life_day=world.life_day,
        reason=(args or {}).get("reason") or "",
    )
    if not result["ok"]:
        if result["reason"] == "already_taken":
            return reject("already_taken", f"You are already on it: {result['existing']}.")
        if result["reason"] == "too_many":
            current = "; ".join(result["current"])
            return reject(
                "too_many",
                f"You already have your hands full: {current}. Finish something first.",
            )
        return reject("bad_task", "That is not something you can take on.")

    return accept(
        f"Noted: you will {result['description']}. It will stay in front of you "
        f"until it is done or the time runs out.",
        goal=result["description"],
    )
