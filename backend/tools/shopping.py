"""看货架与买东西。

信息边界和视野同源：**到店才看得见**，除非你是店主（店主有账本）。
而"东西不能远程拿"——``buy`` 不适用店主那条例外。

超卖的防线不在 ``check_stock``，在 ``economy.buy`` 的原子事务里：
查到的数字从返回那一刻起就是缓存。
"""

from economy import ALL_ITEMS, CATALOG
from tools.base import THOUGHT_FIELD, accept, reject


# --- check_stock / buy：同样不占用游戏时间 ---------------------------

CHECK_STOCK_PARAMETERS = {
    "type": "object",
    "properties": {
        "thought": THOUGHT_FIELD,
        "shop": {
            "type": "string",
            "enum": sorted(CATALOG),
            "description": "Which shop to look at. You must be inside it, unless you own it.",
        },
    },
    "required": ["thought", "shop"],
}


def _shop_access(agent, world, area):
    """能不能查这家店的货架：人在店里，或者你就是店主。

    店主对自己的店有账本，不必亲自站在货架前——这和"店主可以在非营业
    时间进自己的店"是同一条身份特权。这条例外也让"写信问店主"这条路
    真的有价值：否则店主自己都不知道，问了也白问。
    """
    from world import SHOP_OWNERS, area_of

    if SHOP_OWNERS.get(area) == agent.name:
        return True
    here = area_of((world.agent_locations or {}).get(agent.name) or agent.current_location)
    return here == area


def handle_check_stock(agent, args, world=None):
    """查看一家店的货架。

    信息边界和视野是同一条：**你只知道眼前的事**。想知道别处那家店还有
    没有货，要么亲自跑一趟，要么写信问店主——而"写信问"这条路不需要
    任何新代码，它是邮件系统和库存系统组合出来的。

    ⚠️ 查到的数字从返回那一刻起就可能过期。真正的防线在 ``buy`` 里的
    原子扣减，不在这里。
    """
    from economy import CATALOG, economy
    from world import EMPTY_WORLD, SHOP_OWNERS

    world = world or EMPTY_WORLD
    area = (args or {}).get("shop")
    if area not in CATALOG:
        return reject("unknown_shop", f"There is no shop called {area!r} in Valentown.")

    if not _shop_access(agent, world, area):
        owner = SHOP_OWNERS.get(area)
        hint = (
            f" You could write to {owner} and ask."
            if owner else " Nobody runs it, so you would have to go and look."
        )
        return reject(
            "not_in_shop",
            f"You are not at {area}, so you cannot see what is on its shelves.{hint}",
        )

    shelves = economy.stock(area)
    prices = CATALOG[area]["items"]
    in_stock = [
        f"{item} x{count} at {prices[item]} each"
        for item, count in sorted(shelves.items()) if count > 0
    ]
    sold_out = sorted(item for item, count in shelves.items() if count <= 0)

    if not in_stock:
        return accept(f"{area} has sold out of everything today.", stock=shelves)

    lines = "; ".join(in_stock)
    tail = f" Sold out: {', '.join(sold_out)}." if sold_out else ""
    return accept(f"{area} has {lines}.{tail}", stock=shelves)


BUY_PARAMETERS = {
    "type": "object",
    "properties": {
        "thought": THOUGHT_FIELD,
        "item": {
            "type": "string",
            "enum": ALL_ITEMS,
            "description": "What to buy. You must be inside the shop that sells it.",
        },
    },
    "required": ["thought", "item"],
}


def handle_buy(agent, args, world=None):
    """买下一件商品。

    两道关，顺序不能反：

    1. **你得人在卖它的那家店里**（店主也不例外——账本能远程看，东西
       不能远程拿），而且店得开着门；
    2. **扣减必须原子**：库存检查与扣减在 ``inventory.buy`` 的同一把锁里
       完成。先查后扣的写法必然超卖——查到的数字在写回之前就可能被别人
       改掉了。

    卖光时给出的 observation 会带上真实剩余量，好让模型知道"刚才明明
    还有"是怎么回事，从而去别处想办法，而不是原地重试。
    """
    from economy import ITEM_SHOP, economy
    from world import EMPTY_WORLD, area_of

    world = world or EMPTY_WORLD
    item = (args or {}).get("item")
    area = ITEM_SHOP.get(item)
    if area is None:
        return reject("unknown_item", f"Nothing called {item!r} is sold in Valentown.")

    here = area_of((world.agent_locations or {}).get(agent.name) or agent.current_location)
    if here != area:
        return reject(
            "not_in_shop",
            f"{item} is sold at {area}, and you are not there. "
            f"You would have to go to {area} first.",
        )

    if not world.is_open(area, agent.name):
        return reject(
            "closed",
            f"{area} is closed at {world.time_text}; "
            f"it is open {world.opening_hours_text(area)}.",
        )

    result = economy.buy(agent.name, item)
    if not result["ok"]:
        if result["reason"] == "insufficient_funds":
            # 钱不够是**可以想办法**的失败：说清楚差多少，模型才可能去
            # 借钱、换便宜的东西，或者放弃。只说"买不起"等于没说。
            return reject(
                "insufficient_funds",
                f"{item} costs {result['cost']} but you only have {result['balance']}. "
                f"You are {result['short_by']} short — you would need to get money "
                f"from somewhere, or buy something cheaper.",
            )
        return reject(
            "out_of_stock",
            f"{area} has no {item} left ({result['available']} on the shelf). "
            f"Somewhere else, or someone else, might still have some.",
        )

    return accept(
        f"You buy {item} for {result['cost']}. "
        f"You have {result['balance']} left and now carry {result['holding']}; "
        f"{result['remaining']} still on the shelf.",
        purchase=result,
    )


RESTOCK_PARAMETERS = {
    "type": "object",
    "properties": {
        "thought": THOUGHT_FIELD,
        "item": {
            "type": "string",
            "enum": ALL_ITEMS,
            "description": "What to restock. Only for the shop you own.",
        },
        "quantity": {
            "type": "integer",
            "minimum": 1,
            "description": "How many to order in. You pay for each one.",
        },
    },
    "required": ["thought", "item", "quantity"],
}


def handle_restock(agent, args, world=None):
    """店主给自己的店进货。

    这是**经营决策**，不是系统福利：货要自己掏钱，进货价是售价减 2，
    赚的就是这个差价。进多了压钱，进少了断货——什么时候补、补什么，
    由店主自己判断。

    两道关和 ``buy`` 同源：

    1. **只有店主，而且人要在自己店里**。``check_stock`` 那条"店主可以
       远程看账本"的例外在这里不适用——账本能远程看，货得亲手收。
    2. **付钱与上架原子完成**，由 ``economy.restock`` 保证。

    钱不够时按买得起的数量进，并如实告诉店主进了几件、还剩多少钱——
    "钱不够"三个字帮不了他判断下一步。
    """
    from economy import ITEM_SHOP, economy, restock_cost
    from world import EMPTY_WORLD, SHOP_OWNERS, area_of

    world = world or EMPTY_WORLD
    item = (args or {}).get("item")
    area = ITEM_SHOP.get(item)
    if area is None:
        return reject("unknown_item", f"Nothing called {item!r} is sold in Valentown.")

    if SHOP_OWNERS.get(area) != agent.name:
        owner = SHOP_OWNERS.get(area)
        who = f"{owner} runs it" if owner else "nobody runs it"
        return reject(
            "not_the_owner",
            f"You do not own {area} — {who}. You can only restock your own shop.",
        )

    here = area_of((world.agent_locations or {}).get(agent.name) or agent.current_location)
    if here != area:
        return reject(
            "not_in_shop",
            f"You have to be at {area} to take a delivery in. You are not there.",
        )

    result = economy.restock(agent.name, item, (args or {}).get("quantity"))
    if not result["ok"]:
        if result["reason"] == "shelf_full":
            return reject(
                "shelf_full",
                f"The {item} shelf is already full ({result['on_shelf']}/{result['cap']}). "
                f"There is no room for more.",
            )
        return reject(
            "insufficient_funds",
            f"Each {item} costs you {result['unit_cost']} to order in, and you only "
            f"have {result['balance']}. You cannot take in even one.",
        )

    short = ""
    if result["quantity"] < result["requested"]:
        short = (
            f" You wanted {result['requested']} but could only take {result['quantity']}."
        )
    return accept(
        f"You take in {result['quantity']} {item} at {result['unit_cost']} each, "
        f"spending {result['spent']}. The shelf now holds {result['on_shelf']} of "
        f"{result['cap']}, and you have {result['balance']} left.{short}",
        restock=result,
    )
