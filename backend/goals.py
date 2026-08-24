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

GOALS_FILE = Path(__file__).with_name("goals.json")

# 一个人同时最多扛几件事。多了上下文会被任务列表挤满，
# 而且模型会在几件事之间反复横跳、哪件都做不完。
MAX_ACTIVE = 2

DELIVER = "deliver"
ARRIVE = "arrive"
KINDS = (DELIVER, ARRIVE)


@dataclass
class Goal:
    owner: str
    kind: str
    person: str               # deliver: 交给谁；arrive: 谁要到场（通常是自己）
    what: str                 # deliver: 物品名；arrive: 区域名
    deadline_minute: int      # 当天的几点几分之前
    life_day: int
    reason: str = ""          # 人话描述，直接进决策上下文
    status: str = "active"    # active | done | failed
    seq: int = 0

    def describe(self):
        from world import format_clock

        if self.kind == DELIVER:
            who = "yourself" if self.person == self.owner else self.person
            core = f"get {self.what} to {who}"
        else:
            core = f"be at {self.what}"
        tail = f" ({self.reason})" if self.reason else ""
        return f"{core} before {format_clock(self.deadline_minute)}{tail}"

    def is_met(self, world):
        """判定只看世界状态——代码查得到的事实，不是模型的说法。"""
        if self.kind == DELIVER:
            return int((world.holdings.get(self.person) or {}).get(self.what, 0)) > 0
        from world import area_of

        return area_of((world.agent_locations or {}).get(self.person)) == self.what


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
            active = [g for g in self._goals if g.owner == owner and g.status == "active"]
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
        lines = []
        for goal in goals:
            state = "already satisfied" if goal.is_met(world) else "not done yet"
            left = goal.deadline_minute - world.time_minutes
            urgency = f", {max(0, left)} minutes left" if left <= 120 else ""
            lines.append(f"- {goal.describe()} [{state}{urgency}]")
        return "You have taken on:\n" + "\n".join(lines) + "\n"

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
