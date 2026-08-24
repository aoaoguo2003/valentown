"""库存与购买的单元测试。

重点在两条：**超卖只能靠原子扣减挡住**（查询结果永远是过期的），以及
库存信息的边界和视野一致——到店才看得见，除非你是店主。
不涉及任何 LLM 调用。"""

import threading

import pytest

from agents.agent import EmmaHarris, EllaParker, RonParker
from economy import CATALOG, ITEM_SHOP, Economy, price_of
from memory.memory_system import MemorySystem
from tools import get_tool
from world import World


@pytest.fixture
def store(tmp_path):
    return Economy(path=tmp_path / "economy.json")


def _agent(tmp_path, cls=EmmaHarris, location="Emma_home.Living_room"):
    memory = MemorySystem(retention_days=15, memory_dir=tmp_path / "mem")
    memory.initialize_agents(["Emma Harris", "Ron Parker", "Ella Parker"])
    return cls(memory, location)


def _world(minutes=10 * 60, **locations):
    return World(time_minutes=minutes, agent_locations=locations)


# ---------- 商品目录 ----------

def test_catalog_matches_the_agreed_numbers():
    assert set(CATALOG) == {"Supermarket", "Café_bar", "Pharmacy"}
    assert all(price == 4 for price in CATALOG["Supermarket"]["items"].values())
    assert CATALOG["Supermarket"]["daily_stock"] == 3
    assert CATALOG["Café_bar"]["items"] == {"coffee": 8, "tea": 6, "cake": 6}
    assert CATALOG["Café_bar"]["daily_stock"] == 4
    assert all(price == 8 for price in CATALOG["Pharmacy"]["items"].values())
    assert CATALOG["Pharmacy"]["daily_stock"] == 2
    # 稀缺是故意的：药最少，抢购才可能真的发生。
    assert CATALOG["Pharmacy"]["daily_stock"] < CATALOG["Café_bar"]["daily_stock"]


def test_every_item_has_exactly_one_source():
    assert price_of("cold_medicine") == 8
    assert ITEM_SHOP["coffee"] == "Café_bar"
    assert price_of("nothing_like_this") is None


# ---------- 原子扣减：唯一挡得住超卖的地方 ----------

def test_buy_reduces_the_shelf_and_fills_the_bag(store):
    result = store.buy("Emma Harris", "cold_medicine")

    assert result["ok"] is True
    assert result["remaining"] == 1                      # 每日 2 盒，买掉 1
    assert store.holdings("Emma Harris") == {"cold_medicine": 1}
    assert store.count("Pharmacy", "cold_medicine") == 1


def test_buying_past_the_last_one_fails(store):
    # 这个测试要的是"货架空了"，所以先把钱管够——否则 15 块的初始余额
    # 买完第一盒药就只剩 7，先撞上的会是买不起而不是没货。
    store._balances["Emma Harris"] = 100
    for _ in range(2):
        assert store.buy("Emma Harris", "cold_medicine")["ok"] is True

    failed = store.buy("Ron Parker", "cold_medicine")
    assert failed["ok"] is False
    assert failed["reason"] == "out_of_stock"
    assert failed["available"] == 0
    assert store.holdings("Ron Parker") == {}


def test_concurrent_buyers_never_oversell(store):
    # 十个线程抢两盒药：只能有两个成功，一个都不能多。
    # 若写成"先 count 再扣减"，这个测试必然挂。
    results = []
    guard = threading.Lock()
    barrier = threading.Barrier(10)

    def grab(index):
        barrier.wait()
        outcome = store.buy(f"buyer{index}", "cold_medicine")
        with guard:
            results.append(outcome["ok"])

    threads = [threading.Thread(target=grab, args=(i,)) for i in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sum(results) == 2                             # 正好卖出两盒
    assert store.count("Pharmacy", "cold_medicine") == 0
    total_held = sum(
        sum(store.holdings(f"buyer{i}").values()) for i in range(10)
    )
    assert total_held == 2                               # 卖出的和拿到的对得上


def test_stock_snapshot_is_a_copy_and_goes_stale(store):
    snapshot = store.stock("Pharmacy")
    assert snapshot["cold_medicine"] == 2

    store.buy("Emma Harris", "cold_medicine")

    assert snapshot["cold_medicine"] == 2                # 手里那份没变
    assert store.count("Pharmacy", "cold_medicine") == 1  # 真实世界变了


# ---------- 每日补货 ----------

def test_daily_restock_refills_unowned_shops_to_the_cap(store):
    # Café_bar 无人经营，由系统每天补满；补的是"回到上限"而不是累加，
    # 否则卖不掉的东西会堆积，稀缺性几天就没了。
    store._balances["Emma Harris"] = 100
    store.buy("Emma Harris", "coffee")
    store.restock_daily()
    assert store.count("Café_bar", "coffee") == 4

    store.restock_daily()                                # 再补一次
    assert store.count("Café_bar", "coffee") == 4        # 仍是上限，不累加


def test_daily_restock_leaves_owned_shops_alone(store):
    # 有主的店由店主自己掏钱进货，系统不再白送。
    store._balances["Emma Harris"] = 100
    store.buy("Emma Harris", "cold_medicine")
    assert store.count("Pharmacy", "cold_medicine") == 1

    store.restock_daily()

    assert store.count("Pharmacy", "cold_medicine") == 1   # 没人替 Ella 补
    assert store.count("Supermarket", "bread") == 3        # Ron 的店同理，仍是初始满货


def test_restock_does_not_touch_what_people_already_hold(store):
    store.buy("Emma Harris", "cold_medicine")
    store.restock_daily()
    assert store.holdings("Emma Harris") == {"cold_medicine": 1}


def test_state_survives_a_restart(tmp_path):
    path = tmp_path / "economy.json"
    Economy(path=path).buy("Emma Harris", "cold_medicine")

    reopened = Economy(path=path)
    assert reopened.count("Pharmacy", "cold_medicine") == 1
    assert reopened.holdings("Emma Harris") == {"cold_medicine": 1}


# ---------- 信息边界：到店才看得见，除非你是店主 ----------

def _check(agent, world, shop, monkeypatch, store):
    monkeypatch.setattr("economy.economy", store)
    return get_tool("check_stock").handler(
        agent, {"thought": "let me look", "shop": shop}, world)


def test_check_stock_requires_being_in_the_shop(tmp_path, monkeypatch, store):
    emma = _agent(tmp_path)
    world = _world(**{"Emma Harris": "Emma_home.Living_room"})

    result = _check(emma, world, "Pharmacy", monkeypatch, store)

    assert result["ok"] is False
    assert result["reason"] == "not_in_shop"
    # 查不到就提示去问店主——这条路不需要任何新代码，邮件系统已经有了。
    assert "Ella Parker" in result["observation"]


def test_check_stock_works_once_you_are_there(tmp_path, monkeypatch, store):
    emma = _agent(tmp_path, location="Pharmacy.Medicine_shelf")
    world = _world(**{"Emma Harris": "Pharmacy.Medicine_shelf"})

    result = _check(emma, world, "Pharmacy", monkeypatch, store)

    assert result["ok"] is True
    assert "cold_medicine" in result["observation"]
    assert "8" in result["observation"]                  # 单价也看得到


def test_owner_reads_the_ledger_from_anywhere(tmp_path, monkeypatch, store):
    # 店主对自己的店有账本，不必站在货架前——这条例外让"写信问店主"
    # 真的有价值，否则店主自己都不知道。
    ella = _agent(tmp_path, EllaParker, "Ella_home.Kitchen")
    world = _world(**{"Ella Parker": "Ella_home.Kitchen"})

    result = _check(ella, world, "Pharmacy", monkeypatch, store)

    assert result["ok"] is True
    assert "cold_medicine" in result["observation"]


def test_owner_privilege_does_not_extend_to_other_shops(tmp_path, monkeypatch, store):
    ella = _agent(tmp_path, EllaParker, "Ella_home.Kitchen")
    world = _world(**{"Ella Parker": "Ella_home.Kitchen"})

    result = _check(ella, world, "Café_bar", monkeypatch, store)

    assert result["ok"] is False
    # 咖啡馆无人经营，问不到人，只能亲自跑一趟。
    assert "Nobody runs it" in result["observation"]


def test_cafe_has_no_owner_so_nobody_can_check_remotely(tmp_path, monkeypatch, store):
    ron = _agent(tmp_path, RonParker, "Ron_home.Sofa")
    world = _world(**{"Ron Parker": "Ron_home.Sofa"})

    assert _check(ron, world, "Café_bar", monkeypatch, store)["ok"] is False


# ---------- 购买的前置条件 ----------

def _buy(agent, world, item, monkeypatch, store):
    monkeypatch.setattr("economy.economy", store)
    return get_tool("buy").handler(agent, {"thought": "need it", "item": item}, world)


def test_buy_requires_standing_in_the_right_shop(tmp_path, monkeypatch, store):
    emma = _agent(tmp_path, location="Supermarket.Checkout")
    world = _world(**{"Emma Harris": "Supermarket.Checkout"})

    result = _buy(emma, world, "cold_medicine", monkeypatch, store)

    assert result["ok"] is False
    assert result["reason"] == "not_in_shop"
    assert "Pharmacy" in result["observation"]           # 告诉它该去哪
    assert store.count("Pharmacy", "cold_medicine") == 2  # 库存没被动过


def test_owner_ledger_privilege_does_not_apply_to_buying(tmp_path, monkeypatch, store):
    # 账本能远程看，东西不能远程拿。
    ella = _agent(tmp_path, EllaParker, "Ella_home.Kitchen")
    world = _world(**{"Ella Parker": "Ella_home.Kitchen"})

    assert _buy(ella, world, "cold_medicine", monkeypatch, store)["ok"] is False


def test_buy_refused_when_the_shop_is_closed(tmp_path, monkeypatch, store):
    emma = _agent(tmp_path, location="Pharmacy.Medicine_shelf")
    world = _world(minutes=20 * 60, **{"Emma Harris": "Pharmacy.Medicine_shelf"})

    result = _buy(emma, world, "cold_medicine", monkeypatch, store)

    assert result["ok"] is False
    assert result["reason"] == "closed"


def test_successful_buy_reports_price_holding_and_remainder(tmp_path, monkeypatch, store):
    emma = _agent(tmp_path, location="Pharmacy.Medicine_shelf")
    world = _world(**{"Emma Harris": "Pharmacy.Medicine_shelf"})

    result = _buy(emma, world, "cold_medicine", monkeypatch, store)

    assert result["ok"] is True
    observation = result["observation"]
    assert "8" in observation                            # 花了多少
    assert "1" in observation                            # 手上有几个、货架剩几个
    assert store.holdings("Emma Harris") == {"cold_medicine": 1}


def test_sold_out_message_tells_the_model_to_look_elsewhere(tmp_path, monkeypatch, store):
    emma = _agent(tmp_path, location="Pharmacy.Medicine_shelf")
    world = _world(**{"Emma Harris": "Pharmacy.Medicine_shelf"})
    store._balances["Emma Harris"] = 100          # 只想测没货，别被钱挡住
    for _ in range(2):
        _buy(emma, world, "cold_medicine", monkeypatch, store)

    result = _buy(emma, world, "cold_medicine", monkeypatch, store)

    assert result["ok"] is False
    assert result["reason"] == "out_of_stock"
    assert "no cold_medicine left" in result["observation"]


def test_shop_tools_cost_no_game_time():
    assert get_tool("check_stock").terminal is False
    assert get_tool("buy").terminal is False


# ---------- 钱：五件事的原子事务 ----------

def test_buy_moves_money_as_well_as_goods(store):
    # 一次购买要同时改五样：查余额、扣钱、减货架、入袋、店主收钱。
    before_buyer = store.balance("Emma Harris")
    before_owner = store.balance("Ella Parker")          # 药房是 Ella 的

    result = store.buy("Emma Harris", "cold_medicine")

    assert result["ok"] is True
    assert store.balance("Emma Harris") == before_buyer - 8
    assert store.balance("Ella Parker") == before_owner + 8
    assert store.holdings("Emma Harris") == {"cold_medicine": 1}
    assert store.count("Pharmacy", "cold_medicine") == 1


def test_cannot_afford_leaves_everything_untouched(store):
    # 半途失败会留下"钱扣了货没拿到"这种坏账——所以整笔要么全发生，
    # 要么一点都不发生。
    store._balances["Emma Harris"] = 3                   # 买不起 8 块的药
    before_stock = store.count("Pharmacy", "cold_medicine")

    result = store.buy("Emma Harris", "cold_medicine")

    assert result["ok"] is False
    assert result["reason"] == "insufficient_funds"
    assert result["short_by"] == 5
    assert store.balance("Emma Harris") == 3             # 钱没动
    assert store.count("Pharmacy", "cold_medicine") == before_stock   # 货没动
    assert store.holdings("Emma Harris") == {}           # 袋子没动


def test_unowned_shop_keeps_no_takings(store):
    # Café_bar 无人经营，顾客付的钱就此消失——轻微通缩，由社保抵消。
    total_before = sum(store.balances().values()) or 0
    store._balances["Emma Harris"] = 20
    store.buy("Emma Harris", "coffee")                   # 8 块
    assert store.balance("Emma Harris") == 12
    # 没有任何人收到这 8 块。
    assert sum(store.balances().values()) < total_before + 20


def test_starting_purse_cannot_afford_two_medicines(store):
    # 稀缺是故意的：每三天 15 块，一天摊 5 块，一杯 8 块的咖啡都买不起。
    # 借钱因此是必需行为，不是点缀。
    assert store.balance("Emma Harris") == 15
    assert store.buy("Emma Harris", "cold_medicine")["ok"] is True
    second = store.buy("Emma Harris", "cold_medicine")
    assert second["ok"] is False
    assert second["reason"] == "insufficient_funds"


# ---------- 转账：不可逆 ----------

def test_transfer_moves_money_both_ways(store):
    result = store.transfer("Ron Parker", "Emma Harris", 10)

    assert result["ok"] is True
    assert store.balance("Ron Parker") == 5
    assert store.balance("Emma Harris") == 25


def test_transfer_cannot_overdraw(store):
    result = store.transfer("Emma Harris", "Ron Parker", 40)

    assert result["ok"] is False
    assert result["reason"] == "insufficient_funds"
    assert result["short_by"] == 25
    assert store.balance("Emma Harris") == 15            # 一分没动


def test_transfer_rejects_nonsense_amounts(store):
    assert store.transfer("Emma Harris", "Ron Parker", 0)["reason"] == "invalid_amount"
    assert store.transfer("Emma Harris", "Ron Parker", -5)["reason"] == "invalid_amount"
    assert store.transfer("Emma Harris", "Emma Harris", 5)["reason"] == "self_transfer"


def test_concurrent_transfers_never_overdraw(store):
    # 十个线程同时从同一个钱包往外转，每笔 5 块，只有 15 块：
    # 最多成功三笔。先查后转的写法在这里必然透支。
    store._balances["Ron Parker"] = 15
    outcomes = []
    guard = threading.Lock()
    barrier = threading.Barrier(10)

    def send(index):
        barrier.wait()
        result = store.transfer("Ron Parker", f"receiver{index}", 5)
        with guard:
            outcomes.append(result["ok"])

    threads = [threading.Thread(target=send, args=(i,)) for i in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sum(outcomes) == 3
    assert store.balance("Ron Parker") == 0


# ---------- 社保：天数当幂等键 ----------

def test_benefit_is_paid_on_day_one(store):
    result = store.pay_benefit(1, ["Emma Harris", "Ron Parker"])

    assert result["paid"] is True
    assert store.balance("Emma Harris") == 30            # 15 初始 + 15 社保


def test_benefit_only_on_every_third_day(store):
    assert store.pay_benefit(2, ["Emma Harris"])["paid"] is False
    assert store.pay_benefit(3, ["Emma Harris"])["paid"] is False
    assert store.pay_benefit(4, ["Emma Harris"])["paid"] is True
    assert store.pay_benefit(7, ["Emma Harris"])["paid"] is True


def test_paying_the_same_day_twice_does_not_double_the_money(store):
    # /start_new_day 可能被重复调用（网络重试、手滑点两次）。
    # 补货是赋值，重复无害；发钱是累加，必须自己防——用天数当幂等键。
    store.pay_benefit(1, ["Emma Harris"])
    once = store.balance("Emma Harris")

    again = store.pay_benefit(1, ["Emma Harris"])

    assert again["paid"] is False
    assert again["reason"] == "already_paid"
    assert store.balance("Emma Harris") == once          # 一分没多


def test_daily_restock_stays_idempotent_without_any_bookkeeping(store):
    # 和发钱对照：自动补货是"设成上限"，跑几次都一样，不需要任何幂等键。
    # 店主自己进货则是另一回事——那是模型主动发起的意图，每次调用都算数。
    store._balances["Emma Harris"] = 100
    store.buy("Emma Harris", "coffee")
    store.restock_daily()
    store.restock_daily()
    store.restock_daily()
    assert store.count("Café_bar", "coffee") == 4


def test_benefit_ledger_survives_a_restart(tmp_path):
    # 幂等键本身也要持久化，否则重启之后同一天会被再发一次。
    path = tmp_path / "economy.json"
    first = Economy(path=path)
    first.pay_benefit(1, ["Emma Harris"])
    paid = first.balance("Emma Harris")

    reopened = Economy(path=path)
    assert reopened.pay_benefit(1, ["Emma Harris"])["paid"] is False
    assert reopened.balance("Emma Harris") == paid


# ---------- 钱包工具 ----------

def test_check_balance_shows_purse_and_bag(tmp_path, monkeypatch, store):
    monkeypatch.setattr("economy.economy", store)
    emma = _agent(tmp_path)
    store._balances["Emma Harris"] = 42
    store._holdings["Emma Harris"] = {"bread": 2}

    result = get_tool("check_balance").handler(emma, {"thought": "how much do I have"}, None)

    assert result["ok"] is True
    assert "42" in result["observation"]
    assert "bread" in result["observation"]


def test_transfer_tool_reports_the_new_balance(tmp_path, monkeypatch, store):
    monkeypatch.setattr("economy.economy", store)
    emma = _agent(tmp_path)

    result = get_tool("transfer").handler(
        emma, {"thought": "paying them back", "to": "Ron Parker", "amount": 5}, None)

    assert result["ok"] is True
    assert "Ron Parker" in result["observation"]
    assert store.balance("Ron Parker") == 20
    assert store.balance("Emma Harris") == 10


def test_transfer_tool_explains_how_short_you_are(tmp_path, monkeypatch, store):
    # "买不起"三个字帮不了模型；差多少才是它能据此行动的信息。
    monkeypatch.setattr("economy.economy", store)
    emma = _agent(tmp_path)

    result = get_tool("transfer").handler(
        emma, {"thought": "lending a hand", "to": "Ron Parker", "amount": 40}, None)

    assert result["ok"] is False
    assert "25 short" in result["observation"]


def test_buy_tool_explains_the_shortfall(tmp_path, monkeypatch, store):
    monkeypatch.setattr("economy.economy", store)
    emma = _agent(tmp_path, location="Pharmacy.Medicine_shelf")
    world = _world(**{"Emma Harris": "Pharmacy.Medicine_shelf"})
    store._balances["Emma Harris"] = 3

    result = _buy(emma, world, "cold_medicine", monkeypatch, store)

    assert result["ok"] is False
    assert result["reason"] == "insufficient_funds"
    assert "5 short" in result["observation"]
    # 反馈要指出可行的下一步，模型才可能去借钱或换便宜的。
    assert "get money" in result["observation"]


def test_wallet_tools_cost_no_game_time():
    assert get_tool("check_balance").terminal is False
    assert get_tool("transfer").terminal is False


# ---------- 店主进货：经营决策，不是系统福利 ----------

def test_restock_costs_the_owner_money(store):
    # 进货价 = 售价 - 2，差价就是毛利。
    from economy import RESTOCK_MARGIN, restock_cost

    assert RESTOCK_MARGIN == 2
    assert restock_cost("cold_medicine") == 6            # 售价 8
    assert restock_cost("bread") == 2                    # 售价 4

    store._balances["Emma Harris"] = 100
    store.buy("Emma Harris", "cold_medicine")            # 腾出一格
    store._balances["Ella Parker"] = 20

    result = store.restock("Ella Parker", "cold_medicine", 1)

    assert result["ok"] is True
    assert result["spent"] == 6
    assert store.balance("Ella Parker") == 14
    assert store.count("Pharmacy", "cold_medicine") == 2


def test_restock_takes_what_the_purse_allows(store):
    # 钱不够就按买得起的量进——"有多少钱进多少货"让小店能自举，
    # 而不是一次凑不齐整批就永远开不了张。
    store._balances["Emma Harris"] = 100
    store.buy("Emma Harris", "cold_medicine")
    store.buy("Emma Harris", "cold_medicine")            # 货架清空
    store._balances["Ella Parker"] = 7                   # 只够进一件（6）

    result = store.restock("Ella Parker", "cold_medicine", 2)

    assert result["ok"] is True
    assert result["quantity"] == 1                       # 想进 2，只进得起 1
    assert result["requested"] == 2
    assert store.balance("Ella Parker") == 1


def test_restock_cannot_exceed_the_shelf_cap(store):
    # 允许无限囤货的话稀缺就没了。
    store._balances["Ella Parker"] = 100
    result = store.restock("Ella Parker", "cold_medicine", 5)

    assert result["ok"] is False
    assert result["reason"] == "shelf_full"
    assert store.balance("Ella Parker") == 100           # 一分没花


def test_restock_with_an_empty_purse_changes_nothing(store):
    store._balances["Emma Harris"] = 100
    store.buy("Emma Harris", "cold_medicine")
    store._balances["Ella Parker"] = 2                   # 一件都进不起

    result = store.restock("Ella Parker", "cold_medicine", 1)

    assert result["ok"] is False
    assert result["reason"] == "insufficient_funds"
    assert store.balance("Ella Parker") == 2
    assert store.count("Pharmacy", "cold_medicine") == 1


def test_shop_can_bootstrap_from_its_own_takings(store):
    # 开局满货 -> 卖出去 -> 用赚到的钱进货。这就是不给启动资金也能转起来的原因。
    start = store.balance("Ella Parker")
    store._balances["Emma Harris"] = 100
    store.buy("Emma Harris", "cold_medicine")            # Ella 收 8
    store.buy("Emma Harris", "cold_medicine")            # 再收 8

    assert store.balance("Ella Parker") == start + 16
    assert store.count("Pharmacy", "cold_medicine") == 0

    store.restock("Ella Parker", "cold_medicine", 2)     # 花 12 进两件

    assert store.count("Pharmacy", "cold_medicine") == 2
    assert store.balance("Ella Parker") == start + 4     # 净赚 4 = 2 件 x 差价 2


# ---------- 进货工具的资格检查 ----------

def _restock(agent, world, item, quantity, monkeypatch, store):
    monkeypatch.setattr("economy.economy", store)
    return get_tool("restock").handler(
        agent, {"thought": "shelf is looking bare", "item": item, "quantity": quantity}, world)


def test_only_the_owner_may_restock(tmp_path, monkeypatch, store):
    emma = _agent(tmp_path, location="Pharmacy.Medicine_shelf")
    world = _world(**{"Emma Harris": "Pharmacy.Medicine_shelf"})

    result = _restock(emma, world, "cold_medicine", 1, monkeypatch, store)

    assert result["ok"] is False
    assert result["reason"] == "not_the_owner"
    assert "Ella Parker" in result["observation"]


def test_owner_must_be_in_the_shop_to_take_a_delivery(tmp_path, monkeypatch, store):
    # check_stock 那条"店主可远程看账本"的例外在这里不适用：
    # 账本能远程看，货得亲手收。
    ella = _agent(tmp_path, EllaParker, "Ella_home.Kitchen")
    world = _world(**{"Ella Parker": "Ella_home.Kitchen"})

    result = _restock(ella, world, "cold_medicine", 1, monkeypatch, store)

    assert result["ok"] is False
    assert result["reason"] == "not_in_shop"


def test_owner_restocks_successfully_in_the_shop(tmp_path, monkeypatch, store):
    store._balances["Emma Harris"] = 100
    store.buy("Emma Harris", "cold_medicine")
    store._balances["Ella Parker"] = 30

    ella = _agent(tmp_path, EllaParker, "Pharmacy.Boss")
    world = _world(**{"Ella Parker": "Pharmacy.Boss"})

    result = _restock(ella, world, "cold_medicine", 1, monkeypatch, store)

    assert result["ok"] is True
    assert "6" in result["observation"]                  # 单价
    assert store.count("Pharmacy", "cold_medicine") == 2


def test_partial_restock_says_so(tmp_path, monkeypatch, store):
    store._balances["Emma Harris"] = 100
    store.buy("Emma Harris", "cold_medicine")
    store.buy("Emma Harris", "cold_medicine")
    store._balances["Ella Parker"] = 7

    ella = _agent(tmp_path, EllaParker, "Pharmacy.Boss")
    world = _world(**{"Ella Parker": "Pharmacy.Boss"})

    result = _restock(ella, world, "cold_medicine", 2, monkeypatch, store)

    assert result["ok"] is True
    assert "wanted 2" in result["observation"]           # 如实说明只进了一件


def test_restock_costs_no_game_time():
    assert get_tool("restock").terminal is False
