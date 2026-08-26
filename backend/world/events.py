"""事件：世界里**发生过**什么。

上下文一直给的是**当前状态**的快照——你有多少钱、几封未读信、在办什么事。
这套东西补的是另一半：**自从你上次行动以来，有什么变了**。

差别不是修辞。Emma 写信借钱，Gavin 转了 5 块过来——在只有状态的世界里，
她那边**一个字都没有**，只有余额从 3 变成了 8，得她自己发现。转账对收款人
是完全无声的。

这和「在撞墙那一刻指出那条路」是同一条经验：**事情发生的那一刻说一句，
比让它自己盯着一个数字强。**

## ⚠️ 事件不是广播

这是这个模块最容易毁掉整个项目的地方。

小镇的信息不对称是刻意设计的：居民只看得见同区域的人，别人的钱、店里的货、
信的内容都得花动作去取。**要是随手做成"所有人都能看到所有事件"，
这层设计一次就拆没了**——通信系统会立刻失去存在的理由。

所以每条事件都带 ``visible_to``：**谁合法地察觉得到这件事**。

    MONEY_SENT        收款人           钱到账了，他当然知道
    ITEM_GIVEN        接收方           东西到手了
    MEETING_ARRANGED  被约的那一方     约定是两个人的事
    ITEM_BOUGHT       没有人           **别人买了什么，你看不见**
    MAIL_SENT         没有人           见下

## 另一条线：只说状态覆盖不到的事

``visible_to`` 空着不代表这条事件没用——它仍然进日志，供评估和排查。
不进上下文，是因为**当前状态已经说过同样的话了**，再说一遍只是费 token：

    未读信数量  上下文里已经有"你有 2 封未读"    -> MAIL_SENT 不进
    在办的任务  上下文里已经有那条约定           -> MEETING_ARRANGED 只给对方
    余额        只是个数字，看不出"刚刚变过"     -> MONEY_SENT 要进
    背包        同上                             -> ITEM_GIVEN 要进

## 谁来发

**世界服务发，不是工具 handler 发。**``economy.transfer`` 在它那把锁里发，
事件和状态变更原子发生。放在 handler 里的话，任何绕过工具改状态的路径
（比如评估埋场景用的 ``seed``）都会漏——而漏掉的事件不会报错，
只会让某个人永远不知道钱到了。
"""

import threading
from dataclasses import dataclass, field

MAIL_SENT = "MAIL_SENT"
MONEY_SENT = "MONEY_SENT"
ITEM_GIVEN = "ITEM_GIVEN"
ITEM_BOUGHT = "ITEM_BOUGHT"
MEETING_ARRANGED = "MEETING_ARRANGED"


@dataclass(frozen=True)
class Event:
    seq: int
    kind: str
    actor: str                       # 谁干的
    visible_to: frozenset            # 谁察觉得到（**从不包含 actor**，他自己做的）
    life_day: int
    minute: int
    detail: dict = field(default_factory=dict)

    def describe_to(self, watcher):
        """讲给某个人听的一句话。措辞从**他的**角度出发。"""
        detail = self.detail
        if self.kind == MONEY_SENT:
            return f"{self.actor} sent you {detail.get('amount')}."
        if self.kind == ITEM_GIVEN:
            return f"{self.actor} handed you {detail.get('item')}."
        if self.kind == MEETING_ARRANGED:
            return (f"{self.actor} arranged for you both to be at "
                    f"{detail.get('area')} at {detail.get('at')}.")
        if self.kind == MAIL_SENT:
            return f"{self.actor} wrote to you."
        return f"{self.actor} did something ({self.kind})."


class EventLog:
    """一条只增不减的流水，外加每个人读到哪儿了。

    "读到哪儿了"必须记在这里而不是记在居民身上：居民对象每次跑评估都是新建的，
    而这条流水和世界同寿。
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._events = []
        self._seen = {}
        self.life_day = 1
        self.minute = 0

    def set_clock(self, life_day, minute):
        """事件要盖时间戳，而世界服务不知道现在几点。

        调度器（和线上的路由层）在每批决策之前把钟对一下。同一批并发决策
        共用同一个时刻，本来就该如此。
        """
        with self._lock:
            self.life_day, self.minute = life_day, minute

    def record(self, kind, actor, *, visible_to=(), **detail):
        with self._lock:
            event = Event(
                seq=len(self._events),
                kind=kind,
                actor=actor,
                # actor 自己做的事不该再告诉他一遍
                visible_to=frozenset(visible_to) - {actor},
                life_day=self.life_day,
                minute=self.minute,
                detail=detail,
            )
            self._events.append(event)
            return event

    def take_new(self, agent_name):
        """某人**这次**该知道的新事，并把他的水位推到最新。

        ⚠️ 这个方法有副作用，所以**一轮只能调一次**——决策循环里一轮会
        调好几次 ``build_decision_context``，要是每步都取一遍，第一步就把
        事件吃光了，后面几步全看不见。取一次，整轮共用。
        """
        with self._lock:
            start = self._seen.get(agent_name, 0)
            self._seen[agent_name] = len(self._events)
            return [event for event in self._events[start:]
                    if agent_name in event.visible_to]

    def all(self):
        """整条流水——给评估和排查用，不受 ``visible_to`` 限制。"""
        with self._lock:
            return list(self._events)

    def happened(self, kind, **match):
        """发生过这样一件事吗？

        评估的分段判据用它。**比轮询状态准**：很多里程碑是转瞬即逝的——
        Emma 借到钱那一刻余额是 8，买完药就变回 0；药在她手上，交出去就没了。
        状态只能靠每批决策守着看，事件是就是。
        """
        with self._lock:
            return any(
                event.kind == kind
                and all(event.detail.get(key) == value for key, value in match.items())
                for event in self._events
            )

    def reset(self):
        with self._lock:
            self._events.clear()
            self._seen.clear()


event_log = EventLog()
