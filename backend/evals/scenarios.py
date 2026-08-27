"""场景注册表：给小镇埋一个起因，再定一条只看世界状态的判据。

## 为什么要埋

自然跑三天的数据很清楚：模型自发用了 `stay`/`sleep`/`check_weather`/`recall`，
但**通信、转账、任务一次没用**。不是工具的问题——七个人各过各的日子，
谁也不需要谁。**不制造需要，协作永远不会发生。**

## 判据只看世界状态

`holdings("Adam Harris")["cold_medicine"] > 0`。不看模型说没说"我送到了"，
不看它的 thought 写得多漂亮。代码查得到的事实才算数。

⚠️ **判据里不掺行为指标。**"买到了 **且** 没反复撞同一堵墙"——后半句是行为，
不是世界状态，混进 `passed` 就把这条原则搞糊了。行为归 `observability/metrics.py`，
记分卡里两列并排放。

## 场景怎么挑的

真跑数据指着哪儿，就往哪儿出题：

    errand      完整协作链。已有，跑通过一次
    rendezvous  打 `target_absent` 那 44-53 次——他们现在靠走过去碰运气，
                `accept_meeting` 三天只用过 1 次
    scarcity    真跑里从没走到过的路（97.5% 的轮次不改变世界），
                那把防超卖的锁至今没被真正考验过

这个注册表和 `tools/TOOL_REGISTRY` 是同一个形状：**runner 不认识任何具体
场景，就像 runtime 不认识任何具体工具。**
"""

from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class Stage:
    """一道题的一个中间里程碑。``reached(town) -> bool``，只看世界状态。

    ⚠️ **很多里程碑是转瞬即逝的**：Emma 借到钱那一刻余额是 8，买完药就变成 0；
    药在她手上，交出去就没了。所以这些必须**在跑的过程中每批决策查一次**，
    只在最后查等于什么都看不见。runner 记的是**最高水位**。
    """

    name: str
    reached: Callable


@dataclass(frozen=True)
class Scenario:
    name: str
    headline: str                 # 一句话说这题考什么
    setup: str                    # 埋了什么，打印给人看
    seed: Callable                # seed(town) -> None
    judge: Callable               # judge(town) -> {"passed": bool, "detail": str}
    days: int = 1
    max_decisions: int = 60       # 跑到这么多次决策还没达成，就算没做到
    stages: tuple = field(default_factory=tuple)
    """走到哪一步了。

    第一张记分卡的教训：``errand`` 十四格全 ✗，而其中一格其实走完了六环里的
    五环（药已经买到手，只差交付），另一格一个改变世界的动作都没有——
    **它们在记分卡上长得一模一样**。二元判据在多环任务上信号太稀疏，
    区分不出任何消融的差异，那一整列就白跑了。

    分段不动判据：``passed`` 仍然只由 ``judge`` 说了算，这里只是让"卡在哪一环"
    看得见。每一环也仍然只查世界状态。
    """


# --- errand：完整协作链 -------------------------------------------------------

def _seed_errand(town):
    """Gavin 托 Emma 给发烧的 Adam 买药，而她差 5 块钱。

    一个起因串起整条链，每一环都是**真实缺口**，不是硬塞的提示：

      信在收件箱里      -> 她得先读信才知道
      兜里 3 块，药 8 块 -> 不开口借钱就买不成
      Adam 在家等着     -> 买到了还得当面交过去
    """
    town.mailbox.send(
        sender="Gavin Harris",
        recipient="Emma Harris",
        subject="Adam is running a fever",
        body=("Adam has a fever and we are out of cold medicine. Could you get "
              "some from the pharmacy today and bring it to him? I am stuck at "
              "work until this evening."),
        life_day=1,
        time_text="6:30 AM",
    )
    town.economy.seed(balances={"Emma Harris": 3})


def _judge_errand(town):
    got = town.economy.holdings("Adam Harris").get("cold_medicine", 0)
    return {
        "passed": got > 0,
        "detail": (f"Adam 手上的退烧药 {got}｜"
                   f"Emma 手上 {town.economy.holdings('Emma Harris').get('cold_medicine', 0)}｜"
                   f"Emma 余额 {town.economy.balance('Emma Harris')}"),
    }


# --- rendezvous：非见面不可 ---------------------------------------------------

def _seed_rendezvous(town):
    """Arthur 手上有 Mia 想要的东西，两人住在小镇两头。

    东西只能**当面**交（`give_item` 要求同一区域，和转账相反）。所以判据
    虽然只查"Mia 手上有没有蛋糕"，实际逼出来的是：约个时间地点，然后
    两个人都到。

    这一条专门打真跑里的头号拒绝理由 `target_absent`（44-53 次）——
    现在他们的做法是走过去看看人在不在，不在就换个地方再走一趟。
    """
    town.economy.seed(holdings={"Arthur Morgan": {"cake": 1}})
    town.mailbox.send(
        sender="Mia Thompson",
        recipient="Arthur Morgan",
        subject="About that cake you promised",
        body=("You said you would give me that cake. I would rather not spend "
              "the whole day wandering around looking for you — could we agree "
              "on a time and place today, and both be there?"),
        life_day=1,
        time_text="6:30 AM",
    )


def _judge_rendezvous(town):
    got = town.economy.holdings("Mia Thompson").get("cake", 0)
    return {
        "passed": got > 0,
        "detail": (f"Mia 手上的蛋糕 {got}｜"
                   f"Arthur 手上还剩 {town.economy.holdings('Arthur Morgan').get('cake', 0)}｜"
                   f"约定履约 {town.goals.meeting_record()}"),
    }


# --- scarcity：只有一份，两个人都要 --------------------------------------------

def _seed_scarcity(town):
    """货架上只剩一盒退烧药，两个人同时被要求去买，两人的钱都够。

    考两件事，缺一不可：

      **世界不能超卖**——两人并发下单，成交的只能有一个，货架不能变成 -1。
      这条真跑里从没被考验过（97.5% 的轮次一个改变世界的动作都没有），
      那把原子锁写对了，但没人验过它。

      **抢输的那个要换方案**——收到 `out_of_stock` 之后是重新规划，
      还是原地再点一次。
    """
    town.economy.seed(
        stock={"Pharmacy": {"cold_medicine": 1}},
        balances={"Emma Harris": 20, "Mia Thompson": 20},
    )
    for who in ("Emma Harris", "Mia Thompson"):
        town.mailbox.send(
            sender="Gavin Harris",
            recipient=who,
            subject="Cold medicine, today if you can",
            body=("Please pick up cold medicine from the pharmacy today. "
                  "I hear they are nearly out, so do not leave it too late."),
            life_day=1,
            time_text="6:30 AM",
        )


def _judge_scarcity(town):
    emma = town.economy.holdings("Emma Harris").get("cold_medicine", 0)
    mia = town.economy.holdings("Mia Thompson").get("cold_medicine", 0)
    left = town.economy.count("Pharmacy", "cold_medicine")
    sold = emma + mia
    return {
        # 恰好一个人拿到。两个人都拿到 = 超卖，那是世界写错了，比谁都没买到严重。
        "passed": sold == 1 and left >= 0,
        "detail": (f"卖出 {sold}（Emma {emma} / Mia {mia}）｜货架剩 {left}"
                   + ("  ⚠️ 超卖了！" if sold > 1 or left < 0 else "")),
    }


# --- natural：控制组 -----------------------------------------------------------

def _seed_natural(town):
    """什么都不埋。看没有外部起因时，七个人自己会做什么。"""


def _judge_natural(town):
    return {"passed": None, "detail": "控制组，只看行为指标"}


# --- 分段用的小工具 -----------------------------------------------------------

def _read_their_mail(who):
    return lambda town: town.mailbox.unread_counts().get(who, 0) == 0


def _took_on_a_job(who):
    """接下了跨轮的差事。``settle`` 会把落定的任务标掉但不删，所以这一条
    一旦成立就一直成立——正好，它本来就是个里程碑。"""
    return lambda town: any(
        goal.owner == who for goal in town.goals._goals            # noqa: SLF001
    )


def _has(who, item):
    return lambda town: town.economy.holdings(who).get(item, 0) > 0


def _can_afford(who, price):
    return lambda town: town.economy.balance(who) >= price


def _in_the_same_place(first, second):
    """两个人此刻在同一区域。**转瞬即逝**——所以要在跑的过程中查。"""
    def check(town):
        from world.snapshot import area_of

        where = {agent.name: area_of(agent.current_location) for agent in town.agents}
        return where.get(first) is not None and where.get(first) == where.get(second)
    return check


def _anyone_in(area):
    def check(town):
        from world.snapshot import area_of

        return any(area_of(agent.current_location) == area for agent in town.agents)
    return check


SCENARIO_REGISTRY = {
    "errand": Scenario(
        name="errand",
        headline="读信 → 记下任务 → 发现钱不够 → 借钱 → 买 → 当面交付",
        setup=("Gavin 写信托 Emma 给发烧的 Adam 买退烧药；\n"
               "  Emma 兜里 3 块，药 8 块 —— 差 5 块"),
        seed=_seed_errand,
        judge=_judge_errand,
        days=1,
        # 这条链天然要跨半天：药房 9 点才开门，借钱要等一个异步来回，
        # 见面还要再等一次。实测走完要 95-121 次决策，**波动很大**。
        #
        # 一路加上来的：70 -> 三次全部卡在最后一步；120 -> 两次通关、
        # 一次用了 121 次仍然超时。现在给到 300，让它有余量走完。
        #
        # **预算太紧会伪造失败**——那不是"做不到"，是"没跑完"。早停在这里
        # 兜底：达成了就立刻收工，所以富余的预算并不会真的花掉。
        max_decisions=300,
        stages=(
            Stage("读到信", _read_their_mail("Emma Harris")),
            Stage("记下任务", _took_on_a_job("Emma Harris")),
            # 开局 3 块，一天之内没有别的收入（社保三天一次）——
            # 余额到得了 8，只可能是有人转给她。
            Stage("凑够药钱", _can_afford("Emma Harris", 8)),
            Stage("买到药", _has("Emma Harris", "cold_medicine")),
            Stage("和 Adam 碰上面", _in_the_same_place("Emma Harris", "Adam Harris")),
            Stage("交到 Adam 手上", _has("Adam Harris", "cold_medicine")),
        ),
    ),
    "rendezvous": Scenario(
        name="rendezvous",
        headline="东西只能当面交 —— 得先约时间地点，两个人都到",
        setup=("Arthur 手上有一块 Mia 想要的蛋糕，两人住在小镇两头；\n"
               "  Mia 写信提议约个时间地点"),
        seed=_seed_rendezvous,
        judge=_judge_rendezvous,
        days=1,
        # 和 errand 同一个结构性问题：约定要等到点，见面要两人都到。
        # 通关的几次用了 24-46 次决策，失败的几次全部撞在上限上——那是
        # **没跑完**，不是做不到。早停兜着，富余的预算不会真花掉。
        #
        # 150 也不够：基线两次都停在 151，都是 3/4 环（见上面了、蛋糕没递）。
        # 提到 300 是为了**把预算这个嫌疑彻底排除**——再卡在 3/4，那就只能
        # 是模型的问题了。
        max_decisions=300,
        stages=(
            Stage("读到信", _read_their_mail("Arthur Morgan")),
            Stage("约定成立", lambda town: town.goals.meeting_record()["arranged"] > 0),
            Stage("两人碰上面", _in_the_same_place("Arthur Morgan", "Mia Thompson")),
            Stage("蛋糕交到手", _has("Mia Thompson", "cake")),
        ),
    ),
    "scarcity": Scenario(
        name="scarcity",
        headline="只剩一盒药，两个人都要 —— 不能超卖，抢输的要换方案",
        setup=("药房货架上 cold_medicine 只剩 1 盒；\n"
               "  Emma 和 Mia 同时收到信要求今天买到，两人钱都够"),
        seed=_seed_scarcity,
        judge=_judge_scarcity,
        days=1,
        # 通关用 37-46 次，上限 50 —— 贴得太近了。
        max_decisions=120,
        stages=(
            Stage("有人读到信", lambda town: any(
                town.mailbox.unread_counts().get(who, 0) == 0
                for who in ("Emma Harris", "Mia Thompson"))),
            Stage("有人进了药房", _anyone_in("Pharmacy")),
            Stage("药被买走", lambda town: town.economy.count("Pharmacy", "cold_medicine") == 0),
        ),
    ),
    "natural": Scenario(
        name="natural",
        headline="控制组：什么都不埋",
        setup="  什么都不埋",
        seed=_seed_natural,
        judge=_judge_natural,
        days=1,
        max_decisions=40,
    ),
}


def get_scenario(name):
    return SCENARIO_REGISTRY.get(name)
