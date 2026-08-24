"""查天气预报。

当前天气是**免费**的——它随世界快照进决策上下文，抬头就能看见。这个工具
提供的是**未来几小时**：不查预报的话，模型只知道此刻，于是会在晴天做出
"出门野餐三小时"的决定，然后被雨浇。

**抬头看天免费，看预报要花时间**——和现实一致，也正是这个工具值得花掉
一步的理由。
"""

from tools.base import THOUGHT_FIELD, accept

CHECK_WEATHER_PARAMETERS = {
    "type": "object",
    "properties": {
        "thought": THOUGHT_FIELD,
        "hours_ahead": {
            "type": "integer",
            "minimum": 1,
            "maximum": 12,
            "description": "How many hours of forecast you want to look at.",
        },
    },
    "required": ["thought", "hours_ahead"],
}


def handle_check_weather(agent, args, world=None):
    """看接下来几小时的天气。

    数据来自缓存好的当日预报，**不会在这里发起网络请求**——外部调用每个
    游戏日只做一次，绝不放在裁决动作的路径上。所以这个工具本身永远不会
    因为网络问题而失败。
    """
    from weather import describe, is_severe, weather_service
    from world import EMPTY_WORLD, format_clock

    world = world or EMPTY_WORLD
    try:
        hours = int((args or {}).get("hours_ahead") or 6)
    except (TypeError, ValueError):
        hours = 6
    hours = max(1, min(12, hours))

    outlook = weather_service.outlook(world.life_day, world.time_minutes, hours)
    if not outlook:
        return accept("You cannot tell what the weather will do.", forecast=[])

    parts = [f"{format_clock(hour * 60)} {describe(code)}" for hour, code in outlook]
    bad = [f"{format_clock(hour * 60)}" for hour, code in outlook if is_severe(code)]
    warning = (
        f" Outdoor places will be no good around {', '.join(bad)}." if bad else
        " Nothing bad is coming, so outdoor plans should hold."
    )
    return accept(
        "The forecast: " + "; ".join(parts) + "." + warning,
        forecast=[{"hour": hour, "code": code} for hour, code in outlook],
    )
