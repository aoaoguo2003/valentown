"""占用游戏时间的三个工具：去别处、留在原地、睡觉。

它们是仅有的会收敛决策循环的工具——一轮的时钟只能往前推一次，所以
「接下来这段时间你在哪、做什么」这个问题一轮只能回答一次。

``sleep`` 是其中的异类：普通动作最长 180 分钟，它可以横跨整夜。没有它的话，
想睡到天亮得连着决策三次，每次都是一整轮 LLM 调用，纯属白烧。

⚠️ **带前端跑的时候 ``sleep`` 不会被调用。**前端到了 bedTime 就自己接管，
把人走到 ``X_home.Bed`` 睡下，不再请求决策——而 Bed 锚点根本不在
``ALLOWED_DESTINATIONS`` 里（卧室被隐私设计排除了）。它服务的是**没有前端
的路径**：离线试跑、评估集，以及后端自己需要知道"这一天结束了"的时候。
"""

from tools.base import THOUGHT_FIELD, accept, reject
from world.locations import (
    AGENT_NAMES,
    ALLOWED_DESTINATIONS,
    DEFAULT_ACTION_MINUTES,
    MAX_ACTION_MINUTES,
    MAX_SLEEP_MINUTES,
    MIN_ACTION_MINUTES,
    MIN_SLEEP_MINUTES,
    is_outdoor,
)


# --- move_to：占用游戏时间，成功即收敛本轮 ---------------------------

MOVE_TO_PARAMETERS = {
    "type": "object",
    "properties": {
        "thought": THOUGHT_FIELD,
        "action": {
            "type": "string",
            "description": "What to do next, about 10 plain-English words.",
        },
        "destination": {
            "type": "string",
            "enum": ALLOWED_DESTINATIONS,
            "description": "Where to do it. Must be one of the listed anchors.",
        },
        "duration_minutes": {
            "type": "integer",
            "minimum": MIN_ACTION_MINUTES,
            "maximum": MAX_ACTION_MINUTES,
            "description": "How long the action takes, in game minutes.",
        },
        "talk_to": {
            "type": "string",
            "enum": AGENT_NAMES + ["nobody"],
            "description": "Who to talk to while there, or 'nobody'.",
        },
    },
    "required": ["thought", "action", "destination", "duration_minutes", "talk_to"],
}


def handle_move_to(agent, args, world=None):
    """把模型提出的移动意图落实成一个可执行的动作。

    分两道关：

    **结构校验**——目的地必须在白名单内、动作文本不能为空、时长夹到合法
    区间、交谈对象必须确实是别人。失败原因分两类：硬拒绝（目的地非法、
    动作为空）说明结构不可信，整个决策作废；软修复（时长越界、talk_to
    非法）说明意图可信，纠正后照常执行。

    **环境裁决**——营业时间、顾客容量、要找的人在不在。这三条是世界说
    "不"的地方，也是模型必须据此重新规划的地方，所以拒绝时给出的
    observation 必须带足信息量：几点开门、店里有谁、现场都有谁。

    ⚠️ 但拒绝理由**绝不透露对方的去向**。"Bob 不在咖啡馆"是合法反馈，
    "Bob 在公园"不是——后者等于免费给了模型一份全局位置表，通信也就
    没有存在的必要了。想知道某人在哪，只能自己去打听。

    ``world`` 省略时退化为纯结构校验（一切开放、一切有位），供不关心
    环境规则的调用方与单元测试使用。
    """
    from world.snapshot import EMPTY_WORLD, area_of

    world = world or EMPTY_WORLD
    if not isinstance(args, dict):
        return reject("malformed_arguments", "The town could not understand that action.")

    destination = args.get("destination")
    if destination not in ALLOWED_DESTINATIONS:
        return reject(
            "invalid_destination",
            f"{destination!r} is not a place you can go in Valentown.",
        )

    action = str(args.get("action") or "").strip()
    if not action:
        return reject("empty_action", "You did not say what you would actually do there.")

    try:
        duration = int(args.get("duration_minutes"))
    except (TypeError, ValueError):
        duration = DEFAULT_ACTION_MINUTES
    duration = max(MIN_ACTION_MINUTES, min(MAX_ACTION_MINUTES, duration))

    talk_to = args.get("talk_to")
    if talk_to not in AGENT_NAMES or talk_to == agent.name:
        talk_to = "nobody"

    # --- 环境裁决：世界在这里说"不" ---
    area = area_of(destination)

    # 天气是**唯一从外面砸下来**的约束：库存和钱不够是你自己的问题，
    # 大雨则会让一个原本完全可行的计划突然作废。判断按锚点而非区域——
    # Café_bar.Patio 是露台，同一家店里有室内也有户外。
    if is_outdoor(destination) and world.weather_blocks_outdoors():
        return reject(
            "bad_weather",
            f"It is {world.weather_text()} in Valentown right now, so {destination} "
            f"is no place to be. Somewhere indoors would be better.",
        )

    if not world.is_open(area, agent.name):
        return reject(
            "closed",
            f"{area} is closed at {world.time_text}; "
            f"it is open {world.opening_hours_text(area)}.",
        )

    if not world.has_room(area, agent.name):
        # 店里满了是到门口才发现的事，所以可以说清楚现场有谁。
        crowd = ", ".join(world.agents_in_area(area, exclude=agent.name)) or "other people"
        return reject(
            "full",
            f"{area} is full — {crowd} already took the seats. "
            f"Somewhere else might have room.",
        )

    if talk_to != "nobody" and not world.is_present(talk_to, area):
        # 只说"不在这儿"，不说人在哪——想知道去向得靠打听。
        # 三天真跑里这条拒绝出现了 94 次，而模型一次都没想到写信去打听——
        # 因为旧措辞只说"你得先弄清楚他们在哪"，却从不点明**怎么**弄清楚。
        # 在撞墙的那一刻指出那条路，比在系统提示里泛泛叮嘱管用得多。
        return reject(
            "target_absent",
            f"{talk_to} is not at {area}. You could write to them and ask where "
            f"they will be, rather than walking around hoping to run into them.",
        )

    others = world.agents_in_area(area, exclude=agent.name)
    company = f" {', '.join(others)} {'is' if len(others) == 1 else 'are'} here." if others else " Nobody else is here."
    return accept(
        f"You head to {destination} to {action}." + company,
        decision={
            "action": action,
            "destination": destination,
            "duration_minutes": duration,
            "talk_to": talk_to,
        },
    )


# --- stay：同样占用游戏时间，只是不改变位置 -------------------------

STAY_PARAMETERS = {
    "type": "object",
    "properties": {
        "thought": THOUGHT_FIELD,
        "action": {
            "type": "string",
            "description": (
                "What you do without leaving, about 10 plain-English words. "
                "This includes simply waiting for something or someone."
            ),
        },
        "duration_minutes": {
            "type": "integer",
            "minimum": MIN_ACTION_MINUTES,
            "maximum": MAX_ACTION_MINUTES,
            "description": "How long you keep at it, in game minutes.",
        },
        "talk_to": {
            "type": "string",
            "enum": AGENT_NAMES + ["nobody"],
            "description": "Who to talk to while here, or 'nobody'.",
        },
    },
    "required": ["thought", "action", "duration_minutes", "talk_to"],
}


def handle_stay(agent, args, world=None):
    """留在当前位置继续做事——**包括什么也不做，只是等**。

    没有这个工具，居民就只能不停地往别处走：发完一条消息没法原地等回音，
    约了人没法提前到场候着。"等待"是 agent 的基本能力，缺了它，任何需要
    协调的行为都做不完整。

    规则和 ``move_to`` 的差异，全部来自"你已经在那儿了"：

      * **不查容量**——位子本来就是你占着的，满员的店不该把已经坐在
        里面的人赶出去；
      * **仍查营业时间**——打烊了照样得走，这会逼出一次重新规划；
      * **仍查交谈对象在不在**——想搭话的人可能刚离开。

    它也不需要 destination 参数：``move_to`` 的目的地枚举有一百多个取值，
    每次决策都要进 prompt；留在原地本就无处可选，省下的既是 token，
    也是模型选错地方的机会。
    """
    from world.snapshot import EMPTY_WORLD, area_of

    world = world or EMPTY_WORLD
    if not isinstance(args, dict):
        return reject("malformed_arguments", "The town could not understand that action.")

    # 以世界快照为准：它已经合并了前端同步上来的实际位置。
    location = world.agent_locations.get(agent.name) or agent.current_location
    if not location:
        return reject("unknown_location", "You are not anywhere in particular right now.")

    action = str(args.get("action") or "").strip()
    if not action:
        return reject("empty_action", "You did not say what you would actually do.")

    try:
        duration = int(args.get("duration_minutes"))
    except (TypeError, ValueError):
        duration = DEFAULT_ACTION_MINUTES
    duration = max(MIN_ACTION_MINUTES, min(MAX_ACTION_MINUTES, duration))

    talk_to = args.get("talk_to")
    if talk_to not in AGENT_NAMES or talk_to == agent.name:
        talk_to = "nobody"

    area = area_of(location)

    # 天气变坏会把人从露天赶走——这是唯一会主动把人赶走的力量，
    # 和"打烊了待不住"是同一个模式，都会逼出一次重新规划。
    if is_outdoor(location) and world.weather_blocks_outdoors():
        return reject(
            "bad_weather",
            f"It has turned {world.weather_text()} and {location} is out in the open; "
            f"you cannot stay here. Somewhere indoors would be better.",
        )

    # 打烊了就待不住了——注意这里不查容量，位子本来就是你的。
    if not world.is_open(area, agent.name):
        return reject(
            "closed",
            f"{area} has closed for the day at {world.time_text}; you cannot stay. "
            f"It is open {world.opening_hours_text(area)}.",
        )

    if talk_to != "nobody" and not world.is_present(talk_to, area):
        return reject(
            "target_absent",
            f"{talk_to} is not here. You could write to them and ask where they "
            f"will be, rather than waiting on the chance they turn up.",
        )

    others = world.agents_in_area(area, exclude=agent.name)
    company = (
        f" {', '.join(others)} {'is' if len(others) == 1 else 'are'} still here."
        if others else " You are on your own."
    )
    return accept(
        f"You stay at {location} and {action}." + company,
        decision={
            "action": action,
            "destination": location,
            "duration_minutes": duration,
            "talk_to": talk_to,
        },
    )


# --- sleep：唯一能横跨整夜的动作 -------------------------------------

SLEEP_PARAMETERS = {
    "type": "object",
    "properties": {
        "thought": THOUGHT_FIELD,
        "duration_minutes": {
            "type": "integer",
            "minimum": MIN_SLEEP_MINUTES,
            "maximum": MAX_SLEEP_MINUTES,
            "description": (
                "How long you sleep, in game minutes. A full night is around "
                "480 to 540; a short nap is 30 to 90."
            ),
        },
    },
    "required": ["thought", "duration_minutes"],
}


def handle_sleep(agent, args, world=None):
    """睡觉——唯一可以一口气跨越整夜的动作。

    普通动作最长 180 分钟，睡到天亮却要八九个小时。没有这个工具的话，
    模型得连着决策三次才能睡过一夜，每次都是一整轮 LLM 调用，纯属白烧。

    只能在自己家睡：这条不是道德要求，是因为床在家里。至于具体睡在哪个
    锚点——卧室从来不在目的地白名单内（隐私是靠结构保证的），所以就地
    在自家任何位置睡下，不另外移动。

    动作文本刻意写成含 "sleep" 的句子：``agent_state`` 靠关键词判断这次
    动作算不算休息，从而重置 energy 锚点。有了这个工具之后，那个判断第一次
    有了明确来源，而不是从自由文本里猜。
    """
    from world.snapshot import EMPTY_WORLD, area_of

    world = world or EMPTY_WORLD
    location = (world.agent_locations or {}).get(agent.name) or agent.current_location
    if not location:
        return reject("unknown_location", "You are not anywhere in particular right now.")

    if area_of(location) != agent.home_area:
        return reject(
            "not_at_home",
            f"You cannot bed down at {location} — your bed is at {agent.home_area}. "
            f"You would have to go home first.",
        )

    try:
        duration = int((args or {}).get("duration_minutes"))
    except (TypeError, ValueError):
        duration = 8 * 60
    duration = max(MIN_SLEEP_MINUTES, min(MAX_SLEEP_MINUTES, duration))

    hours = duration / 60
    return accept(
        f"You sleep at {location} for about {hours:.1f} hours.",
        decision={
            "action": f"sleep for {duration} minutes",
            "destination": location,
            "duration_minutes": duration,
            "talk_to": "nobody",
        },
    )
