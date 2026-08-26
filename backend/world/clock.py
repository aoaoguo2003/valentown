"""游戏时钟：时间文本和分钟数之间的换算。

整个 ``world/`` 包最底层的模块——**一个项目模块都不 import**，所以谁都能
安全地拿它，包括 ``agents/state.py``。

这两个函数原本一个住在 ``agent_state.py``、一个住在 ``world.py``：同一件事
分在两处，还逼得"世界"去 import"居民"。收到一起纯粹是把它们放回该在的地方。
"""

import re


def parse_clock_to_minutes(clock_text):
    """把 "7:00 AM" 这样的时钟文本换成当天的第几分钟。

    解析不了就返回早上六点——时间是决策的骨架，宁可给个安全的默认值，
    也不能让一个格式错误把整轮决策掀翻。
    """
    match = re.match(r"^\s*(\d{1,2})(?::(\d{2}))?\s*(AM|PM)\s*$", str(clock_text or ""), re.I)
    if not match:
        return 6 * 60

    hours = int(match.group(1))
    minutes = int(match.group(2) or 0)
    period = match.group(3).upper()
    if period == "PM" and hours != 12:
        hours += 12
    if period == "AM" and hours == 12:
        hours = 0
    return (hours * 60) + minutes


def format_clock(minutes):
    """把游戏内分钟数格式化成前端同款的 "7:00 AM" 时钟文本。"""
    minutes = int(minutes) % (24 * 60)
    hour24, minute = divmod(minutes, 60)
    suffix = "AM" if hour24 < 12 else "PM"
    return f"{hour24 % 12 or 12}:{minute:02d} {suffix}"
