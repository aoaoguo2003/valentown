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
class Scenario:
    name: str
    headline: str                 # 一句话说这题考什么
    setup: str                    # 埋了什么，打印给人看
    seed: Callable                # seed(town) -> None
    judge: Callable               # judge(town) -> {"passed": bool, "detail": str}
    days: int = 1
    max_decisions: int = 60       # 跑到这么多次决策还没达成，就算没做到
    watch: tuple = field(default_factory=tuple)   # 想在记分卡里额外看到的东西


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


SCENARIO_REGISTRY = {
    "errand": Scenario(
        name="errand",
        headline="读信 → 记下任务 → 发现钱不够 → 借钱 → 买 → 当面交付",
        setup=("Gavin 写信托 Emma 给发烧的 Adam 买退烧药；\n"
               "  Emma 兜里 3 块，药 8 块 —— 差 5 块"),
        seed=_seed_errand,
        judge=_judge_errand,
        days=1,
        max_decisions=70,
    ),
    "rendezvous": Scenario(
        name="rendezvous",
        headline="东西只能当面交 —— 得先约时间地点，两个人都到",
        setup=("Arthur 手上有一块 Mia 想要的蛋糕，两人住在小镇两头；\n"
               "  Mia 写信提议约个时间地点"),
        seed=_seed_rendezvous,
        judge=_judge_rendezvous,
        days=1,
        max_decisions=70,
    ),
    "scarcity": Scenario(
        name="scarcity",
        headline="只剩一盒药，两个人都要 —— 不能超卖，抢输的要换方案",
        setup=("药房货架上 cold_medicine 只剩 1 盒；\n"
               "  Emma 和 Mia 同时收到信要求今天买到，两人钱都够"),
        seed=_seed_scarcity,
        judge=_judge_scarcity,
        days=1,
        max_decisions=50,
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
