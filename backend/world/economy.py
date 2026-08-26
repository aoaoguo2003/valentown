"""经济系统：商店货架、个人物品栏、以及每个人的钱。

这一层是**世界状态**，不是工具：数据和原子操作放在这里，"谁有资格看、
谁有资格买"的判断留在 tools/ 里。工具是门，这里是房间。

## 为什么货和钱在同一个模块、同一把锁下

买一件东西要**同时**改五样状态：

    查余额够不够 -> 扣买家的钱 -> 减货架 -> 入买家袋子 -> 加店主的钱

它们必须一起成功或一起失败。半途失败会留下"钱扣了货没拿到"这种坏账；
而如果钱和货分属两把锁，除了部分失败，两个线程还可能各持一把互相等待，
形成循环等待死锁。

**需要一起原子改变的状态，就该由同一把锁保护**——原子性边界决定了模块
边界，这也是把库存和钱包合成一个模块的全部理由。

## 两种更新，一种天然幂等，一种不是

    补货:  stock = 上限        赋值，跑两次结果一样  -> 天然幂等
    发钱:  balance += 15       累加，跑两次钱翻倍    -> 必须自己防

``/start_new_day`` 可能被重复调用（网络重试、手滑点两次），所以社保发放
用**天数当幂等键**：这一天发过就不再发。补货则不需要任何保护。

## 店主的钱从哪来、到哪去

开局每家店都是满货，所以店主第一天就有东西可卖。此后**有主的店由店主
自己掏钱进货**：进货价是售价减 2，差价就是毛利。钱不够就按买得起的量进，
小店因此能自举起来。Café_bar 无人经营，收支中性，继续由系统每日补满。

## 稀缺是故意的

每人每三天 15 块，一天摊下来 5 块，而一杯咖啡就要 8 块——**一天连杯咖啡
都买不起**。药每天只补两盒。不制造稀缺，超卖那条代码路径永远走不到，
居民之间也不会为任何东西产生真正的竞争，更不会需要开口借钱。
"""

import json
import threading
from pathlib import Path

from config import DATA_DIR

ECONOMY_FILE = DATA_DIR / "economy.json"

# 除了店主，没有人有职业收入：每人每三天领一次社保。
# 一天摊下来 5 块，买不起一杯 8 块的咖啡——借钱因此是必需行为，不是点缀。
BENEFIT_AMOUNT = 15
BENEFIT_INTERVAL_DAYS = 3
INITIAL_BALANCE = 15          # 相当于开局先发一次，否则第一天谁都动不了

# 店主的收入来自卖货：顾客付的钱直接进他口袋。
# 但货不是白来的——店主要按**进货价**自掏腰包补货，赚的是这个差价。
RESTOCK_MARGIN = 2            # 进货价 = 售价 - 2

# Café_bar 无人经营：它的钱进虚空，货也从虚空来，收支中性，
# 因此保留每日自动补满。有主的店则完全由店主自己决定进什么、进多少。

# 每家店卖什么、单价多少、每天补货补到几件。
# ``daily_stock`` 是**补满到**这个数，不是每天累加，这样稀缺程度才稳定。
CATALOG = {
    "Supermarket": {
        "daily_stock": 3,
        "items": {
            "bread": 4,
            "milk": 4,
            "eggs": 4,
            "apples": 4,
            "vegetables": 4,
        },
    },
    "Café_bar": {
        "daily_stock": 4,
        "items": {
            "coffee": 8,
            "tea": 6,
            "cake": 6,
        },
    },
    "Pharmacy": {
        "daily_stock": 2,
        "items": {
            "cold_medicine": 8,
            "painkiller": 8,
            "bandage": 8,
            "vitamins": 8,
        },
    },
}

# 所有商品名的扁平集合，供工具的参数 schema 使用。
ALL_ITEMS = sorted({item for shop in CATALOG.values() for item in shop["items"]})

# 谁经营哪家店——顾客付的钱进他口袋。这是唯一的定义处。
#
# 它曾经被复制成两份（这里一份、world.py 一份），因为那时 world.py 顶层要
# import tools，tools 顶层要 import economy，从 economy 反向导入 world 就成环。
# locations.py 搬进 world/ 之后 snapshot.py 不再依赖 tools，环没了，
# 复制也就跟着删了。
SHOP_OWNERS = {
    "Supermarket": "Ron Parker",
    "Pharmacy": "Ella Parker",
}

# 每件商品在哪家店卖（每样东西只有一个来源，不做跨店比价）。
ITEM_SHOP = {
    item: area for area, shop in CATALOG.items() for item in shop["items"]
}


def price_of(item):
    area = ITEM_SHOP.get(item)
    return CATALOG[area]["items"][item] if area else None


def restock_cost(item):
    """店主进一件货要花多少。差价就是他的毛利。"""
    price = price_of(item)
    return max(1, price - RESTOCK_MARGIN) if price is not None else None


def shop_of(item):
    return ITEM_SHOP.get(item)


class Economy:
    def __init__(self, path=ECONOMY_FILE):
        self.path = Path(path)
        self._lock = threading.Lock()
        state = self._load()
        self._stock = state.get("stock") or {}
        self._holdings = state.get("holdings") or {}
        self._balances = state.get("balances") or {}
        self._paid_days = set(state.get("paid_benefit_days") or [])
        if not self._stock:
            self._stock = self._full_shelves()
            with self._lock:
                self._save()

    # --- 查询：结果天生就是过期的 -----------------------------------

    def stock(self, area):
        """某家店此刻的货架：``{商品: 件数}``。

        ⚠️ 返回的是一份**拷贝**，而且从拿到它的那一刻起就可能过时。
        绝不能用它做"先查再扣"的判断——那正是超卖的写法。
        """
        with self._lock:
            return dict(self._stock.get(area) or {})

    def count(self, area, item):
        with self._lock:
            return int((self._stock.get(area) or {}).get(item, 0))

    def holdings(self, agent_name):
        """某人身上有什么。任务是否达成（比如"药到手了没"）就看这里。"""
        with self._lock:
            return dict(self._holdings.get(agent_name) or {})

    # --- 改动：唯一可信的那道防线 -----------------------------------

    def balance(self, agent_name):
        """某人还有多少钱。和库存快照一样，拿到那一刻起就可能过期。"""
        with self._lock:
            return int(self._balances.get(agent_name, INITIAL_BALANCE))

    def balances(self):
        with self._lock:
            return dict(self._balances)

    def all_holdings(self):
        """每个人手上有什么——供构造世界快照、判定任务用。"""
        with self._lock:
            return {name: dict(bag) for name, bag in self._holdings.items()}

    def buy(self, agent_name, item, quantity=1):
        """买一件东西：**五件事在同一把锁里原子完成**。

            查余额够不够 -> 扣买家的钱 -> 减货架 -> 入买家袋子 -> 加店主的钱

        任何一步不满足就整笔不发生，绝不会留下"钱扣了货没拿到"这种坏账。
        这也是防超卖的唯一有效位置：调用方此前查到的库存和余额都只是缓存，
        只有这里的检查算数，所以失败信息里带上真实数字，好让上层把"刚才
        明明还有"如实反馈给模型。
        """
        area = ITEM_SHOP.get(item)
        if area is None:
            return {"ok": False, "reason": "unknown_item", "item": item}

        quantity = max(1, int(quantity or 1))
        price = CATALOG[area]["items"][item]
        cost = price * quantity

        with self._lock:
            shelf = self._stock.setdefault(area, {})
            available = int(shelf.get(item, 0))
            if available < quantity:
                return {
                    "ok": False,
                    "reason": "out_of_stock",
                    "item": item,
                    "area": area,
                    "available": available,
                }

            purse = int(self._balances.get(agent_name, INITIAL_BALANCE))
            if purse < cost:
                return {
                    "ok": False,
                    "reason": "insufficient_funds",
                    "item": item,
                    "area": area,
                    "price": price,
                    "cost": cost,
                    "balance": purse,
                    "short_by": cost - purse,
                }

            shelf[item] = available - quantity
            bag = self._holdings.setdefault(agent_name, {})
            bag[item] = int(bag.get(item, 0)) + quantity
            self._balances[agent_name] = purse - cost

            # 顾客付的钱进店主口袋；无人经营的店（Café_bar），钱就此消失。
            owner = SHOP_OWNERS.get(area)
            if owner and owner != agent_name:
                self._balances[owner] = int(
                    self._balances.get(owner, INITIAL_BALANCE)) + cost

            self._save()
            return {
                "ok": True,
                "item": item,
                "area": area,
                "quantity": quantity,
                "price": price,
                "cost": cost,
                "balance": self._balances[agent_name],
                "remaining": shelf[item],
                "holding": bag[item],
            }

    def give(self, giver, receiver, item, quantity=1):
        """把东西交到另一个人手上：**两侧的袋子在同一把锁里一起改**。

        和 ``transfer`` 一样不可逆，也一样必须原子——先查后给的写法会在
        并发下把同一件东西给出去两次。

        这里不检查两人在不在一起，那是 handler 的事：**能力边界归门，
        数据与原子操作归房间**。
        """
        if giver == receiver:
            return {"ok": False, "reason": "self_gift"}

        try:
            quantity = int(quantity)
        except (TypeError, ValueError):
            return {"ok": False, "reason": "invalid_quantity"}
        if quantity <= 0:
            return {"ok": False, "reason": "invalid_quantity"}

        with self._lock:
            bag = self._holdings.setdefault(giver, {})
            held = int(bag.get(item, 0))
            if held < quantity:
                return {
                    "ok": False,
                    "reason": "not_carrying",
                    "item": item,
                    "held": held,
                    "wanted": quantity,
                }

            bag[item] = held - quantity
            if bag[item] == 0:
                del bag[item]
            other = self._holdings.setdefault(receiver, {})
            other[item] = int(other.get(item, 0)) + quantity
            self._save()
            return {
                "ok": True,
                "item": item,
                "quantity": quantity,
                "receiver": receiver,
                "left": bag.get(item, 0),
                "receiver_now_has": other[item],
            }

    def transfer(self, sender, recipient, amount):
        """把钱转给另一位居民：**检查与两侧过账在同一把锁里完成**。

        这是不可逆的：钱一旦转出就收不回来，没有撤销这回事。所以余额检查
        必须和过账原子完成——先查后转的写法会在并发下转出比余额更多的钱。
        """
        if sender == recipient:
            return {"ok": False, "reason": "self_transfer"}

        try:
            amount = int(amount)
        except (TypeError, ValueError):
            return {"ok": False, "reason": "invalid_amount"}
        if amount <= 0:
            return {"ok": False, "reason": "invalid_amount"}

        with self._lock:
            purse = int(self._balances.get(sender, INITIAL_BALANCE))
            if purse < amount:
                return {
                    "ok": False,
                    "reason": "insufficient_funds",
                    "amount": amount,
                    "balance": purse,
                    "short_by": amount - purse,
                }

            self._balances[sender] = purse - amount
            self._balances[recipient] = int(
                self._balances.get(recipient, INITIAL_BALANCE)) + amount
            self._save()
            return {
                "ok": True,
                "amount": amount,
                "recipient": recipient,
                "balance": self._balances[sender],
            }

    def pay_benefit(self, life_day, agent_names):
        """每三天发一次社保。**用天数当幂等键。**

        ``/start_new_day`` 可能被重复调用（网络重试、手滑点两次）。补货是
        赋值操作，跑两次结果一样；发钱是累加，跑两次钱就翻倍——所以这里
        必须自己记住"这一天发过了"，而补货什么都不用做。
        """
        life_day = int(life_day or 1)
        if life_day % BENEFIT_INTERVAL_DAYS != 1:
            return {"paid": False, "reason": "not_a_payout_day"}

        with self._lock:
            if life_day in self._paid_days:
                return {"paid": False, "reason": "already_paid", "life_day": life_day}

            for name in agent_names:
                self._balances[name] = int(
                    self._balances.get(name, INITIAL_BALANCE)) + BENEFIT_AMOUNT
            self._paid_days.add(life_day)
            self._save()
            return {
                "paid": True,
                "life_day": life_day,
                "amount": BENEFIT_AMOUNT,
                "balances": dict(self._balances),
            }

    def restock_daily(self):
        """每日自动补货——**只补无人经营的店**。

        有主的店由店主自己掏钱进货（见 ``restock``），所以这里不碰它们；
        Café_bar 没有店主，也就没有经营决策，由"看不见的手"每天补满。

        补的是**回到上限**而不是累加：累加的话卖不掉的东西会无限堆积，
        稀缺性几天就消失了。也正因为是赋值，这个操作**天然幂等**——
        ``/start_new_day`` 被重复调用也无害，不像发钱那样需要幂等键。
        """
        with self._lock:
            for area, shop in CATALOG.items():
                if SHOP_OWNERS.get(area):
                    continue                      # 有主的店：店主自己进货
                self._stock[area] = {item: shop["daily_stock"] for item in shop["items"]}
            self._save()
            return {area: dict(items) for area, items in self._stock.items()}

    def restock(self, agent_name, item, quantity=1):
        """店主进货：**付钱与上架在同一把锁里原子完成**。

        进货价是售价减去 ``RESTOCK_MARGIN``，差价就是店主的毛利。钱不够
        就按买得起的数量进——"有多少钱进多少货"让小店能自举起来，而不是
        一次凑不齐整批就永远开不了张。

        货架上限仍是 ``daily_stock``：允许无限囤货的话，稀缺性就没有了，
        居民之间也不会再为任何东西竞争。

        这个方法不做身份与位置检查，那是 handler 的事——**能力边界归门，
        数据与原子操作归房间**。
        """
        area = ITEM_SHOP.get(item)
        if area is None:
            return {"ok": False, "reason": "unknown_item", "item": item}

        cap = CATALOG[area]["daily_stock"]
        unit_cost = restock_cost(item)
        quantity = max(1, int(quantity or 1))

        with self._lock:
            shelf = self._stock.setdefault(area, {})
            on_shelf = int(shelf.get(item, 0))
            room = cap - on_shelf
            if room <= 0:
                return {
                    "ok": False,
                    "reason": "shelf_full",
                    "item": item,
                    "on_shelf": on_shelf,
                    "cap": cap,
                }

            purse = int(self._balances.get(agent_name, INITIAL_BALANCE))
            affordable = purse // unit_cost
            taken = min(quantity, room, affordable)
            if taken <= 0:
                return {
                    "ok": False,
                    "reason": "insufficient_funds",
                    "item": item,
                    "unit_cost": unit_cost,
                    "balance": purse,
                    "short_by": unit_cost - purse,
                }

            spent = taken * unit_cost
            shelf[item] = on_shelf + taken
            self._balances[agent_name] = purse - spent
            self._save()
            return {
                "ok": True,
                "item": item,
                "area": area,
                "quantity": taken,
                "requested": quantity,
                "unit_cost": unit_cost,
                "spent": spent,
                "balance": self._balances[agent_name],
                "on_shelf": shelf[item],
                "cap": cap,
            }

    def seed(self, *, balances=None, holdings=None, stock=None):
        """把世界直接摆成某个样子——**仅供测试与评估埋场景**。

        生产路径上钱和货只能通过 buy / give / transfer / restock 流动，
        那几条路上有锁、有校验、有原子性。这个方法把它们全绕开了。

        单独开一个方法，而不是让调用方自己去改 ``_balances``，是为了让
        "绕过规则改状态"这件事在代码里显形——搜一下 ``.seed(`` 就能找齐
        所有埋点。散在各处的私有属性赋值做不到这一点。
        """
        with self._lock:
            for name, amount in (balances or {}).items():
                self._balances[name] = int(amount)
            for name, bag in (holdings or {}).items():
                self._holdings[name] = {item: int(count) for item, count in bag.items()}
            for area, shelf in (stock or {}).items():
                self._stock.setdefault(area, {}).update(
                    {item: int(count) for item, count in shelf.items()})
            self._save()

    def reset(self):
        """清空持有、货架补满——仅供测试与重新开局。"""
        with self._lock:
            self._stock = self._full_shelves()
            self._holdings = {}
            self._balances = {}
            self._paid_days = set()
            self._save()

    # --- 内部实现 ---------------------------------------------------

    def _full_shelves(self):
        return {
            area: {item: shop["daily_stock"] for item in shop["items"]}
            for area, shop in CATALOG.items()
        }

    def _load(self):
        if not self.path.exists():
            return {}
        try:
            with self.path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except (json.JSONDecodeError, OSError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save(self):
        """临时文件 + 原子替换。调用方必须已持有 ``self._lock``。"""
        payload = {
            "stock": self._stock,
            "holdings": self._holdings,
            "balances": self._balances,
            "paid_benefit_days": sorted(self._paid_days),
        }
        temp_path = self.path.with_name(f".{self.path.name}.{threading.get_ident()}.tmp")
        with temp_path.open("w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
        temp_path.replace(self.path)


# 全局单例，和 mailbox / persona_store 的用法一致。
economy = Economy()
