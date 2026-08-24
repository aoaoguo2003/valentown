"""决策循环：把"想一次就结束"变成"想 → 做 → 看 → 再想"。

    State_t → LLM → Action → Tool → Environment → Observation → State_t+1 → ...

改造前每个 tick 只发生一次 LLM 调用：模型被强制填一张表，程序照着执行，
环境永远说 yes。这里补上三件缺的事——模型自己**选**工具、环境可以**拒绝**、
被拒之后带着理由**重来**。

## 循环怎么停

三个出口，缺一不可：

  ① 行动类工具成功  —— 拿到可播放的动作，正常收敛
  ② 步数用完        —— 护栏，防止模型反复撞墙烧钱
  ③ LLM 不可用      —— 立刻兜底，不空转重试

出口 ① 依赖 ``ToolSpec.terminal``，而它的判据是**占不占用游戏时间**：
查记忆、看信、查天气都不占用，再成功也不收敛，因为本轮还没回答「接下来
这段时间你在哪、做什么」；只有 move_to / stay 这类占用时间的工具成功了，
时钟才能往前推，前端才有动画可播。

判据不是「改不改变世界」——发一封信改变了世界却不占时间，若判它收敛，
这一轮就在时钟没动的情况下结束，下一轮立刻重来，白白空转一次请求。

循环因此不需要认识任何具体工具。

## 锁怎么用

LLM 调用最长 60 秒，绝不能持锁进行——改造前整个决策包在全局锁里，七个居民
彻底串行。这里只在两个瞬间进锁：**取世界快照**和**提交决策**，中间的思考与
执行全在锁外。

于是出现一个真实的并发问题：**决策依据的世界，和提交决策时的世界，不是同一个
世界**。模型思考的几十秒里，别人可能已经坐进了最后一个座位。所以提交前必须
拿最新快照重新裁决一次，被拒就带着"位子被抢了"回到循环重新规划。这和电商
"下单那一刻要重新校验库存"是同一件事——看到的库存是缓存，成交与否以提交
那一刻的真相为准。
"""

# 用模块引用而不是 `from goals import goal_store`：后者在加载时就绑死了
# 对象，测试和离线试跑替换单例时会失效，结果写进真实存档。
import goals
from observability import log_action_event, trace_operation
from tools import function_schemas, get_tool

# 一轮之内允许的最大工具调用次数。绝大多数决策一步就收敛（没被拒绝），
# 被拒后重来两三步通常够用；这个上限是护栏，不是常态。
MAX_STEPS = 5


def _summarise_args(args):
    """把工具参数压成一行，供 scratchpad 回灌给模型看。"""
    interesting = [f"{key}={value!r}" for key, value in (args or {}).items() if key != "thought"]
    return ", ".join(interesting)


def run_decision_loop(agent, *, internal_state, triggers, day_number, time_text,
                      current_location, last_action, with_world, max_steps=MAX_STEPS):
    """驱动一个居民做出下一个动作。

    ``with_world(fn)`` 由调用方提供：它负责加锁、构造当前世界快照、
    以最新快照调用 ``fn``，并返回结果。循环本身因此完全不需要知道锁的
    存在，路由层也不需要知道裁决细节。

    返回 ``(decision, steps)``。``steps`` 是本轮完整的工具调用轨迹，
    既回灌给模型，也原样返回给调用方写进响应和追踪日志。
    """
    scratchpad = []

    for step in range(max_steps):
        # ── 想：世界快照 + 本轮试错记录 → 让模型自己挑工具 ──
        world = with_world(lambda current: current)

        # 先结算任务再组装上下文：达成的和过期的都要立刻从眼前撤下，
        # 否则模型会对着一件已经做完的事继续忙活。成败都写进记忆——
        # 没有痕迹的话，反思看不到，居民也学不会上次为什么没做到。
        for settled in goals.goal_store.settle(agent.name, world):
            _remember_settled(agent, settled, day_number)
        context = agent.build_decision_context(
            internal_state, triggers, day_number, time_text, current_location,
            last_action=last_action,
            scratchpad=scratchpad,
            visible_agents=world.visible_agents(agent.name),
            unread_letters=world.unread_for(agent.name),
            balance=world.balance_for(agent.name),
            weather=world.weather_text(),
            tasks=goals.goal_store.summary_for(agent.name, world),
        )

        with trace_operation("decision", agent.name):
            call = agent.llm.call_tools(agent.name, context, function_schemas(agent.name))

        if call is None:                                    # ③ LLM 不可用
            return _give_up(agent, triggers, scratchpad, day_number, time_text,
                            reason="llm_unavailable")

        spec = get_tool(call["name"])
        if spec is None:                                    # 模型编了个不存在的工具
            scratchpad.append({
                "tool": call["name"],
                "summary": _summarise_args(call["args"]),
                "thought": call["args"].get("thought"),
                "ok": False,
                "reason": "unknown_tool",
                "observation": f"There is no tool called {call['name']!r}.",
            })
            continue

        # 同一轮里重复问同一个问题：直接把上次的答案还给它。
        # 真跑两天的数据显示这是最大的浪费来源——有几轮五步全花在反复
        # 查同一个货架和同一个余额上，一个动作都没做出来。纯查询的答案
        # 一轮之内不会变，再查一遍只是白烧一步。
        if spec.read_only:
            previous = next(
                (entry for entry in scratchpad
                 if entry["tool"] == spec.name
                 and entry["summary"] == _summarise_args(call["args"])
                 and entry["ok"]),
                None,
            )
            if previous:
                scratchpad.append({
                    "tool": spec.name,
                    "summary": _summarise_args(call["args"]),
                    "thought": call["args"].get("thought"),
                    "ok": False,
                    "reason": "already_known",
                    "observation": (
                        f"You already checked that this turn. The answer was: "
                        f"{previous['observation']} Act on it instead of looking again."
                    ),
                })
                continue

        # 每轮调用次数上限：护栏本身也是数据驱动的，循环只数次数，
        # 不需要知道"发信"或"查记忆"各自该限几次。没有它，模型可能
        # 一轮连发四封信，步数耗尽却什么正事都没做。
        if spec.max_per_turn:
            used = sum(1 for entry in scratchpad if entry["tool"] == spec.name and entry["ok"])
            if used >= spec.max_per_turn:
                scratchpad.append({
                    "tool": spec.name,
                    "summary": _summarise_args(call["args"]),
                    "thought": call["args"].get("thought"),
                    "ok": False,
                    "reason": "rate_limited",
                    "observation": (
                        f"You have already used {spec.name} {used} time(s) this turn. "
                        f"Do something else now."
                    ),
                })
                continue

        # ── 做：交给工具自己的 handler，锁外执行（查询类不碰共享状态）──
        result = spec.handler(agent, call["args"], world)

        # ── 提交：行动类成功了才进锁，并对照最新世界重新裁决一次 ──
        if result["ok"] and spec.terminal:
            result = with_world(lambda current: _commit(agent, spec, call["args"], current))

        entry = {
            "tool": spec.name,
            "summary": _summarise_args(call["args"]),
            "thought": call["args"].get("thought"),
            "ok": result["ok"],
            "reason": result.get("reason"),
            "observation": result["observation"],
        }
        scratchpad.append(entry)
        log_action_event({
            "agent_name": agent.name,
            "life_day": day_number,
            "time_text": time_text,
            "step": step,
            "terminal": spec.terminal,
            **entry,
        })

        if result["ok"] and spec.terminal:                  # ① 正常收敛
            agent.last_observation = result["observation"]
            decision = dict(result["decision"])
            decision["source"] = "llm"
            return decision, scratchpad

        # 查询类成功 → 带着新信息继续想
        # 任何失败   → 带着拒绝理由继续想

    return _give_up(agent, triggers, scratchpad, day_number, time_text,   # ② 步数用完
                    reason="max_steps_exhausted")


def _remember_settled(agent, goal, day_number):
    """任务落定时写一条记忆。成败都要留痕，反思才看得到。"""
    verb = "finished" if goal.status == "done" else "failed to"
    try:
        agent.update_memory(
            f"I {verb} {goal.describe()}.",
            category="task",
            importance=7 if goal.status == "done" else 6,
            life_day=day_number,
        )
    except Exception:                       # noqa: BLE001  记忆写失败不能拖垮决策
        pass


def _commit(agent, spec, args, world):
    """在最新世界快照下重新裁决并落地。

    重跑一次 handler 而不是复用先前的结果，是因为那个结果依据的快照
    可能已经过期——模型思考期间，别人可能占掉了最后一个座位，或者店
    刚好打了烊。裁决通过才写入世界状态。
    """
    result = spec.handler(agent, args, world)
    if result["ok"]:
        agent.current_location = result["decision"]["destination"]
    return result


def _give_up(agent, triggers, scratchpad, day_number, time_text, reason):
    """确定性兜底：无论模型表现如何，一轮必须产出一个可执行的动作，
    模拟不能卡住。兜底只去自己家和公园，本来就不会被环境规则拒绝。"""
    decision = agent.fallback_next_action(triggers)
    decision["source"] = "fallback"
    log_action_event({
        "agent_name": agent.name,
        "life_day": day_number,
        "time_text": time_text,
        "step": len(scratchpad),
        "tool": "fallback",
        "summary": _summarise_args(decision),
        "ok": True,
        "reason": reason,
        "observation": f"Fell back to {decision['destination']}.",
    })
    agent.current_location = decision["destination"]
    return decision, scratchpad
