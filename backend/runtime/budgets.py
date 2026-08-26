"""预算：一个居民一天最多花掉多少。

`MAX_STEPS` 管的是**一轮**想几步，这里管的是**一天**总共花多少。两者拦的
不是同一种失控：前者防"在一轮里反复撞墙"，后者防"轮数本身失控"——
加一个居民、把 `MAX_STEPS` 从 5 调到 10、场景多跑两天，账都会翻倍，
而没有任何东西会拦住它。

⚠️ **这是一道正常情况下永远不会响的闸。**实测一个居民一天约 17–34 次调用，
默认上限设在 120 次 / 500k token，跑十趟也碰不到。这是它该有的样子——
护栏响了就说明出事了。代价是它在真实运行里没被验证过，只有故障注入测过。

## 撞到上限之后

**不抛异常，走确定性兜底**，和「LLM 不可用」同一条路：模拟不能卡住，
前端还等着一个可播放的动作。日志里的 `reason` 是 `budget_exhausted`，
和 `llm_unavailable` 分开——一个是没钱了，一个是打不通，混在一起
排查时会走冤枉路。

## token 只能事后记账

花了多少 token 要等接口回来才知道，所以这里拦的永远是**下一次**调用：
"你今天已经花了 X，不许再开始新的了"。想在调用前就精确管住，得先估算
prompt 长度——那是另一套东西，而且估不准反而会误伤。
"""

from collections import defaultdict


class Budget:
    """按「居民 + 天」记账。

    没有 `Budget` 对象时一切照旧——`run_decision_loop` 的 `budget` 默认是
    None，生产路径上不开这道闸。
    """

    def __init__(self, *, calls_per_day=120, tokens_per_day=500_000):
        self.calls_per_day = calls_per_day
        self.tokens_per_day = tokens_per_day
        self._calls = defaultdict(int)
        self._tokens = defaultdict(int)

    # --- 记账 -----------------------------------------------------------

    def record(self, agent_name, life_day, tokens=0):
        key = (agent_name, life_day)
        self._calls[key] += 1
        self._tokens[key] += int(tokens or 0)

    def usage(self, agent_name, life_day):
        key = (agent_name, life_day)
        return {"calls": self._calls[key], "tokens": self._tokens[key]}

    # --- 查闸 -----------------------------------------------------------

    def exceeded(self, agent_name, life_day):
        """超了就返回一句人话，没超返回 None。

        返回话而不是布尔值，是为了让日志和 observation 都能说清楚
        **是哪一项**超了——"预算用完了"这种话排查时等于没说。
        """
        key = (agent_name, life_day)
        if self.calls_per_day and self._calls[key] >= self.calls_per_day:
            return (f"{agent_name} has already made {self._calls[key]} model calls "
                    f"on day {life_day} (limit {self.calls_per_day})")
        if self.tokens_per_day and self._tokens[key] >= self.tokens_per_day:
            return (f"{agent_name} has already spent {self._tokens[key]} tokens "
                    f"on day {life_day} (limit {self.tokens_per_day})")
        return None

    # --- 报账 -----------------------------------------------------------

    def report(self):
        """跑完之后看看离上限还有多远。

        护栏没响不代表设得合适——**离上限还有多远**才说明它是不是形同虚设。
        """
        if not self._calls:
            return {"agent_days": 0}
        calls = list(self._calls.values())
        tokens = list(self._tokens.values())

        # 两项额度各自算占比，然后取所有「人 x 天 x 项」里最高的那一个。
        # ⚠️ 别把两项打包成元组再 max ——那比的是元组的字典序，
        # 返回的也是元组不是数。第一版就是这么写的，测试当场抓到。
        ratios = []
        for key in self._calls:
            if self.calls_per_day:
                ratios.append(self._calls[key] / self.calls_per_day)
            if self.tokens_per_day:
                ratios.append(self._tokens[key] / self.tokens_per_day)

        return {
            "agent_days": len(self._calls),
            "calls": {"max": max(calls), "total": sum(calls),
                      "limit": self.calls_per_day},
            "tokens": {"max": max(tokens), "total": sum(tokens),
                       "limit": self.tokens_per_day},
            "closest_to_the_limit": round(max(ratios, default=0.0), 3),
        }
