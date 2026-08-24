"""随身之物：钱和东西——都是一瞬间就能交出去的，因此都不占用游戏时间。

除了店主，没有人有职业收入：每人每三天领 15 块社保，一天摊下来 5 块，
而一杯咖啡就要 8 块。**在这个小镇上，开口借钱是必需行为而不是点缀。**

转账**不需要见面**，像手机转账一样。要求跑一趟的话，链条会变成
"约见面 -> 见面 -> 转账"，而稀缺本来就已经够紧；更何况"瞬间完成"这件事
本身就和"要跑一趟"矛盾。

⚠️ 转账是**不可逆**的：钱一旦转出就收不回来，没有撤销。所以余额检查
必须和过账在同一把锁里原子完成，先查后转的写法会在并发下透支。

⭐ 但 ``give_item`` 有一条和 ``transfer`` **相反**的规则：**东西必须当面
递过去**，钱不用。这个不对称是有道理的——转账像手机转账，一瞬间隔空完成；
把一瓶牛奶交给别人，得两个人站在一起。它也是"帮别人跑腿"这类任务唯一的
终点：没有它，买到的东西永远送不出去。
"""

from tools.base import THOUGHT_FIELD, accept, reject
from tools.locations import AGENT_NAMES

CHECK_BALANCE_PARAMETERS = {
    "type": "object",
    "properties": {"thought": THOUGHT_FIELD},
    "required": ["thought"],
}


def handle_check_balance(agent, args, world=None):
    """看看自己还有多少钱，以及身上带着什么。

    只看得到**自己的**——别人有多少钱是私事，想知道只能开口问。
    """
    from economy import economy

    purse = economy.balance(agent.name)
    bag = economy.holdings(agent.name)
    carried = ", ".join(f"{item} x{count}" for item, count in sorted(bag.items()) if count > 0)
    tail = f" You are carrying {carried}." if carried else " You are carrying nothing."
    return accept(f"You have {purse} in your purse.{tail}", balance=purse, holdings=bag)


TRANSFER_PARAMETERS = {
    "type": "object",
    "properties": {
        "thought": THOUGHT_FIELD,
        "to": {
            "type": "string",
            "enum": AGENT_NAMES,
            "description": "Which resident receives the money.",
        },
        "amount": {
            "type": "integer",
            "minimum": 1,
            "description": "How much to send. You cannot send more than you have.",
        },
    },
    "required": ["thought", "to", "amount"],
}


def handle_transfer(agent, args, world=None):
    """把钱转给另一位居民。

    改变世界却不占游戏时间，和写信同类——转完账还能接着决定"接下来这段
    时间做什么"，比如去药房把药买了。

    ⚠️ 不可逆：转错了没有撤销。所以宁可在这里多拒绝，也不能事后补救。
    """
    from economy import economy

    recipient = (args or {}).get("to")
    if recipient not in AGENT_NAMES:
        return reject("unknown_recipient", f"There is nobody called {recipient!r} in Valentown.")
    if recipient == agent.name:
        return reject("self_transfer", "Moving money to yourself changes nothing.")

    result = economy.transfer(agent.name, recipient, (args or {}).get("amount"))
    if not result["ok"]:
        if result["reason"] == "invalid_amount":
            return reject("invalid_amount", "You have to send a positive amount.")
        return reject(
            "insufficient_funds",
            f"You only have {result['balance']}, so you cannot send "
            f"{result['amount']} — you are {result['short_by']} short.",
        )

    return accept(
        f"You send {result['amount']} to {recipient}. You have {result['balance']} left. "
        f"They will notice it the next time they check their purse.",
        transfer=result,
    )


GIVE_ITEM_PARAMETERS = {
    "type": "object",
    "properties": {
        "thought": THOUGHT_FIELD,
        "to": {
            "type": "string",
            "enum": AGENT_NAMES,
            "description": "Which resident you hand it to. They must be here with you.",
        },
        "item": {
            "type": "string",
            "description": "What you hand over. You have to be carrying it.",
        },
    },
    "required": ["thought", "to", "item"],
}


def handle_give_item(agent, args, world=None):
    """把随身携带的东西交给眼前的人。

    ⚠️ 和 ``transfer`` 相反：**必须面对面**。钱可以隔空转，东西得当面递。
    所以这里要查对方在不在同一个区域——而拒绝理由**依然不能说对方在哪**，
    信息不对称的规矩对每一个工具一视同仁。

    这是"帮别人跑腿"唯一的终点。没有它，Emma 买到的药永远送不到 Adam
    手上，"给某人带样东西"这类任务也就永远无法判定完成。
    """
    from economy import economy
    from world import EMPTY_WORLD, area_of

    world = world or EMPTY_WORLD
    receiver = (args or {}).get("to")
    if receiver not in AGENT_NAMES:
        return reject("unknown_recipient", f"There is nobody called {receiver!r} in Valentown.")
    if receiver == agent.name:
        return reject("self_gift", "Handing something to yourself changes nothing.")

    item = str((args or {}).get("item") or "").strip()
    if not item:
        return reject("no_item", "You did not say what you were handing over.")

    here = area_of((world.agent_locations or {}).get(agent.name) or agent.current_location)
    if not world.is_present(receiver, here):
        return reject(
            "target_absent",
            f"{receiver} is not here with you, and you cannot hand something over "
            f"from a distance. You could write and arrange where to meet.",
        )

    result = economy.give(agent.name, receiver, item)
    if not result["ok"]:
        return reject(
            "not_carrying",
            f"You are not carrying any {item}, so you have nothing to give.",
        )

    return accept(
        f"You hand {item} to {receiver}. They now have {result['receiver_now_has']}; "
        f"you have {result['left']} left.",
        gift=result,
    )
