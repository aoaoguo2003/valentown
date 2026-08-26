"""任务：让居民能记住一件要做的事，跨越好几轮决策。

## 为什么需要它

改造前的居民是**需求驱动**的——饿了去吃、累了去睡。需求有两个特点让它
不需要任何"记性"：**它自己会响**（数值超阈值），而且**一轮就能满足**
（去厨房吃饭）。

任务不是这样。"给 Adam 买退烧药"要跨好几轮：读信 → 出门 → 到药房 → 买 →
送过去，中间隔着几个游戏小时。而每一轮的决策上下文都是**重新组装**的，
scratchpad 一收敛就扔。所以没有一个专门的地方记着这件事的话，居民下一轮
就不记得自己在干嘛了。

真跑两天的数据印证了这一点：模型有好几轮把五步全花在查东西上，一个动作
都没做出来——**不知道自己要干嘛，就只能把能查的都查一遍**。

## 完成判定必须是世界状态，不能让模型自己宣布

绝不能让 agent 说"我做完了"——它会声称成功。判定只认代码查得到的事实：

    deliver   economy.holdings(某人)[某物] > 0
    arrive    某人此刻在某个区域

这也是评估的前提：**没有客观判定，就说不出"任务成功率 70%"**，因为根本
没有"这件事算不算做完"的定义。而且这样既不需要人工标注答案，也不需要
另找一个 LLM 当裁判。

## 期限用「当天几点之前」

不是"几天内"。两天的模拟里跨天的目标基本没机会完成，而当天的期限能让
"来不及了"真的发生——**有期限压力，才会出现取舍**。
"""

import json
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path

from config import DATA_DIR
from world import events

GOALS_FILE = DATA_DIR / "goals.json"

# 每一类任务同时最多扛几件。分类计数而不是总量计数：跑腿和赴约是两回事，
# 手上有一件差事不该妨碍你答应见个面。多了上下文会被任务列表挤满，
# 而且模型会在几件事之间反复横跳、哪件都做不完。
MAX_ACTIVE = 2

# 约定之前要留出的余量。到点才醒来是来不及的——还得走过去。
COMMITMENT_BUFFER_MINUTES = 15

DELIVER = "deliver"
ARRIVE = "arrive"
MEET = "meet"
KINDS = (DELIVER, ARRIVE, MEET)


@dataclass
class Goal:
    owner: str
    kind: str
    person: str               # deliver: 交给谁；arrive/meet: 对方是谁
    what: str                 # deliver: 物品名；arrive/meet: 区域名
    deadline_minute: int      # 当天的几点几分之前
    life_day: int
    reason: str = ""          # 人话描述，直接进决策上下文
    status: str = "active"    # active | done | failed
    seq: int = 0

    def describe(self):
        from world.clock import format_clock

        if self.kind == DELIVER:
            who = "yourself" if self.person == self.owner else self.person
            core = f"get {self.what} to {who}"
            when = f"before {format_clock(self.deadline_minute)}"
        elif self.kind == MEET:
            core = f"meet {self.person} at {self.what}"
            when = f"at {format_clock(self.deadline_minute)}"
        else:
            core = f"be at {self.what}"
            when = f"before {format_clock(self.deadline_minute)}"
        tail = f" ({self.reason})" if self.reason else ""
        return f"{core} {when}{tail}"

    def is_met(self, world):
        """判定只看世界状态——代码查得到的事实，不是模型的说法。"""
        from world.snapshot import area_of

        if self.kind == DELIVER:
            return int((world.holdings.get(self.person) or {}).get(self.what, 0)) > 0

        locations = world.agent_locations or {}
        if self.kind == MEET:
            # **双方**都得在场。约会不是"我到了"，是"我们碰上了"——
            # 只查自己的话，一个人在空荡荡的公园干等也算履约了。
            return (area_of(locations.get(self.owner)) == self.what
                    and area_of(locations.get(self.person)) == self.what)

        return area_of(locations.get(self.person)) == self.what


class GoalStore:
    def __init__(self, path=GOALS_FILE):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._goals = [Goal(**row) for row in self._load()]

    # --- 对外接口 ---------------------------------------------------

    def accept(self, owner, kind, person, what, deadline_minute, life_day, reason=""):
        """接下一件事。超过同时在办的上限就拒绝——扛太多等于一件都做不成。"""
        if kind not in KINDS:
            return {"ok": False, "reason": "unknown_kind"}

        with self._lock:
            active = [g for g in self._goals
                      if g.owner == owner and g.status == "active" and g.kind == kind]
            if len(active) >= MAX_ACTIVE:
                return {
                    "ok": False,
                    "reason": "too_many",
                    "current": [g.describe() for g in active],
                }
            duplicate = next(
                (g for g in active if g.kind == kind and g.person == person and g.what == what),
                None,
            )
            if duplicate:
                return {"ok": False, "reason": "already_taken", "existing": duplicate.describe()}

            goal = Goal(
                owner=owner, kind=kind, person=person, what=what,
                deadline_minute=int(deadline_minute), life_day=int(life_day),
                reason=str(reason or "")[:120],
                seq=max((g.seq for g in self._goals), default=0) + 1,
            )
            self._goals.append(goal)
            self._save()
            return {"ok": True, "goal": goal, "description": goal.describe()}

    def arrange_meeting(self, first, second, area, at_minute, life_day, reason=""):
        """一次约定，给**双方各建一个** goal，共享时间与地点。

        为什么不是"我记下来、再写信告诉你"：那样两个人的记录会各自漂移，
        而且判定得同时查两份。共享同一个时间地点、各自持有一份，双方的
        上下文里就都会出现它，谁没到场也一目了然。

        对方随后会在自己的决策上下文里看到这个约定——接受的动作直接改变了
        双方的世界状态，不需要再回一封确认信。
        """
        outcomes = []
        for owner, other in ((first, second), (second, first)):
            outcomes.append(self.accept(
                owner=owner, kind=MEET, person=other, what=area,
                deadline_minute=at_minute, life_day=life_day, reason=reason,
            ))
        if all(result["ok"] for result in outcomes):
            from world.clock import format_clock

            events.event_log.record(events.MEETING_ARRANGED, first,
                                    visible_to={second},
                                    area=area, at=format_clock(at_minute),
                                    other=second)
            return {"ok": True, "description": outcomes[0]["description"]}

        # 有一方没排上就整体作废，绝不留下单边的约定——
        # 一个人以为约好了、另一个人根本不知道，比没约还糟。
        with self._lock:
            self._goals = [
                goal for goal in self._goals
                if not (goal.kind == MEET and goal.what == area
                        and goal.deadline_minute == at_minute
                        and goal.status == "active"
                        and {goal.owner, goal.person} == {first, second})
            ]
            self._save()
        failed = next(result for result in outcomes if not result["ok"])
        return {"ok": False, "reason": failed["reason"], "detail": failed}

    def next_deadline(self, owner, life_day):
        """这个人手上最早的一个截止时刻；没有在办的事就返回 None。

        约会的时刻和任务的期限在这里是同一回事——**都是"不能睡过头"的
        那个点**。一个九小时的午觉能把当天所有约定和差事一并作废。
        """
        pending = self.active_for(owner, life_day)
        return min((goal.deadline_minute for goal in pending), default=None)

    def meeting_record(self):
        """履约统计：约了几次、成了几次。

        这是这套系统唯一的原创指标，而且它衡量的东西很具体——当"马上要
        赴约"和"我饿了"撞在一起时，模型会怎么选。
        """
        meets = [goal for goal in self._goals if goal.kind == MEET]
        honored = sum(1 for goal in meets if goal.status == "done")
        broken = sum(1 for goal in meets if goal.status == "failed")
        settled = honored + broken
        return {
            "arranged": len(meets) // 2,          # 一次约定两条记录
            "honored": honored // 2 if honored else 0,
            "broken": broken,
            "rate": round(honored / settled, 3) if settled else None,
        }

    def active_for(self, owner, life_day):
        with self._lock:
            return [
                g for g in self._goals
                if g.owner == owner and g.status == "active" and g.life_day == life_day
            ]

    def settle(self, owner, world):
        """结算某人的在办任务：达成的标 done，过期的标 failed。

        返回刚刚变更状态的任务，供调用方写进记忆——**任务的成败必须留下
        痕迹**，否则反思看不到，居民也永远学不会自己上次为什么没做到。
        """
        changed = []
        with self._lock:
            for goal in self._goals:
                if goal.owner != owner or goal.status != "active":
                    continue
                if goal.life_day != world.life_day:
                    goal.status = "failed"          # 跨天即作废，期限是当天的
                    changed.append(goal)
                elif goal.is_met(world):
                    goal.status = "done"
                    changed.append(goal)
                elif world.time_minutes >= goal.deadline_minute:
                    goal.status = "failed"
                    changed.append(goal)
            if changed:
                self._save()
        return changed

    def summary_for(self, owner, world):
        """给决策上下文用的一段话。

        任务**免费**进上下文，和未读信数量、余额、当前天气同级——真跑的
        数据已经证明，不进上下文的东西模型就会忘。
        """
        goals = self.active_for(owner, world.life_day)
        if not goals:
            return ""
        from world.clock import format_clock

        lines = []
        due_now = []
        for goal in goals:
            state = "already satisfied" if goal.is_met(world) else "not done yet"
            left = goal.deadline_minute - world.time_minutes
            urgency = f", {max(0, left)} minutes left" if left <= 120 else ""
            lines.append(f"- {goal.describe()} [{state}{urgency}]")
            # 约会临近时单独顶到最前面。三天真跑显示模型连上一步查过的余额
            # 都记不住，三小时前的约定更不可能自己想起来——所以这一行必须是
            # 免费、强制、按时出现的，不能指望它去检索记忆。
            if goal.kind == MEET and 0 <= left <= 90 and not goal.is_met(world):
                due_now.append(
                    f"You are due at {goal.what} at "
                    f"{format_clock(goal.deadline_minute)} to meet {goal.person}, "
                    f"and it is now {world.time_text}."
                )
        head = "".join(f"{line}\n" for line in due_now)
        return head + "You have taken on:\n" + "\n".join(lines) + "\n"

    def stats(self):
        from collections import Counter

        with self._lock:
            return Counter(goal.status for goal in self._goals)

    def reset(self):
        with self._lock:
            self._goals = []
            self._save()

    # --- 内部实现 ---------------------------------------------------

    def _load(self):
        if not self.path.exists():
            return []
        try:
            with self.path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except (json.JSONDecodeError, OSError):
            return []
        return data if isinstance(data, list) else []

    def _save(self):
        temp_path = self.path.with_name(f".{self.path.name}.{threading.get_ident()}.tmp")
        with temp_path.open("w", encoding="utf-8") as file:
            json.dump([asdict(goal) for goal in self._goals], file,
                      ensure_ascii=False, indent=2)
        temp_path.replace(self.path)


goal_store = GoalStore()
