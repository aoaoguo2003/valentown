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

# 一律用模块引用，不写 `from world.goals import goal_store`：后者在加载时就
# 绑死了对象，替换单例时会失效——测试和离线试跑会把结果写进真实存档。
#
# `tools` 同理，而且多一层理由：**消融实验靠替换 tools.function_schemas
# 和 tools.get_tool 来摘掉某件工具**（关掉一个能力再跑，看任务达成率掉多少）。
# 写成 `from tools import function_schemas` 的话，这个循环在加载时就拿到了
# 原版函数，摘不掉——而摘不掉的后果不是报错，是消融组和基线组跑出一样的
# 数字，看上去像"这个能力没用"。
import tools
import world.events as events
import world.goals as goals
from observability import current_context, log_action_event, trace_operation

# 一轮之内允许的最大工具调用次数。绝大多数决策一步就收敛（没被拒绝），
# 被拒后重来两三步通常够用；这个上限是护栏，不是常态。
MAX_STEPS = 5


def _summarise_args(args):
    """把工具参数压成一行，供 scratchpad 回灌给模型看。"""
    interesting = [f"{key}={value!r}" for key, value in (args or {}).items() if key != "thought"]
    return ", ".join(interesting)


def _record(scratchpad, context, *, tool, args, ok, reason, observation, terminal=None):
    """把一步同时写进 scratchpad 和追踪日志。

    这两件事必须一起发生：scratchpad 是给模型看的，日志是给我们看的，
    少了任何一边都会得到一份自相矛盾的记录。曾经有三个提前 continue 的
    分支只做了前者，于是被拦下的重复查询、超限的调用、模型编造的工具名
    在追踪文件里完全不存在——而那恰恰是"无效调用率"要统计的东西。

    合成一个函数是为了让"只做一半"在结构上不可能，而不是靠记得。
    """
    entry = {
        "tool": tool,
        "summary": _summarise_args(args),
        "thought": (args or {}).get("thought"),
        "ok": ok,
        "reason": reason,
        "observation": observation,
    }
    scratchpad.append(entry)
    log_action_event({**context, "step": len(scratchpad) - 1, "terminal": terminal, **entry})
    return entry


def run_decision_loop(agent, *, internal_state, triggers, day_number, time_text,
                      current_location, last_action, with_world, max_steps=MAX_STEPS,
                      filter_tools=False, budget=None, omit_context=()):
    """驱动一个居民做出下一个动作。

    ``with_world(fn)`` 由调用方提供：它负责加锁、构造当前世界快照、
    以最新快照调用 ``fn``，并返回结果。循环本身因此完全不需要知道锁的
    存在，路由层也不需要知道裁决细节。

    返回 ``(decision, steps)``。``steps`` 是本轮完整的工具调用轨迹，
    既回灌给模型，也原样返回给调用方写进响应和追踪日志。
    """
    scratchpad = []
    trace = {"agent_name": agent.name, "life_day": day_number, "time_text": time_text}

    # ⚠️ **一轮只取一次。**``take_new`` 有副作用（推进已读水位），而下面
    # 每一步都会重新组装上下文——每步取一遍的话，第一步就把事件吃光了，
    # 后面几步全看不见，而且不会报错。
    recent = tuple(events.event_log.take_new(agent.name))

    for step in range(max_steps):
        # ── 想：世界快照 + 本轮试错记录 → 让模型自己挑工具 ──
        world = with_world(lambda current: current)

        # 先结算任务再组装上下文：达成的和过期的都要立刻从眼前撤下，
        # 否则模型会对着一件已经做完的事继续忙活。成败都写进记忆——
        # 没有痕迹的话，反思看不到，居民也学不会上次为什么没做到。
        for settled in goals.goal_store.settle(agent.name, world):
            _remember_settled(agent, settled, day_number)

        # 手上在办的事也进日志。回看一条轨迹时，"他当时想干什么"和
        # "他做了什么"必须摆在一起，否则只能看到一串孤立的工具调用。
        active = goals.goal_store.active_for(agent.name, day_number)
        trace["goal"] = active[0].describe() if active else None
        # 任务点名了什么物品，就把那几样的价钱一起给他。**不给整张价目表。**
        wanted = tuple(dict.fromkeys(
            goal.what for goal in active if goal.kind == goals.DELIVER))
        # 此刻用不了的工具：schema 不进请求，但下面会以一行的形式进
        # 上下文。摘的是字数，不是能力——看不见的能力不会被规划。
        if filter_tools:
            schemas, hidden = tools.schemas_for_now(agent, world)
        else:
            schemas, hidden = tools.function_schemas(agent.name), []

        context = agent.build_decision_context(
            internal_state, triggers, day_number, time_text, current_location,
            last_action=last_action,
            scratchpad=scratchpad,
            visible_agents=world.visible_agents(agent.name),
            unread_letters=world.unread_for(agent.name),
            balance=world.balance_for(agent.name),
            holdings=world.holdings_for(agent.name),
            weather=world.weather_text(),
            tasks=goals.goal_store.summary_for(agent.name, world),
            hidden_tools=hidden,
            wanted_items=wanted,
            recent_events=recent,
            omit_context=omit_context,
        )

        # 一天的总账。MAX_STEPS 管一轮想几步，这里管一天花多少——
        # 两者拦的不是同一种失控。撞上了走兜底，和 LLM 不可用同一条路。
        if budget:
            over = budget.exceeded(agent.name, day_number)
            if over:
                return _give_up(agent, triggers, scratchpad, day_number, time_text,
                                reason="budget_exhausted")

        with trace_operation("decision", agent.name):
            call = agent.llm.call_tools(agent.name, context, schemas)
            # 把这一步的 trace_id 抄进动作日志。两份日志本来各记各的，
            # 对不上——于是"这一步花了多少 token"这个问题永远答不了。
            # 一个 id 就把行为和成本缝在了一起。
            trace["trace_id"] = current_context().get("trace_id")
            if budget:
                budget.record(agent.name, day_number,
                              agent.llm.last_usage.get("total_tokens", 0))

        if call is None:                                    # ③ LLM 不可用
            return _give_up(agent, triggers, scratchpad, day_number, time_text,
                            reason="llm_unavailable")

        spec = tools.get_tool(call["name"])
        if spec is None:                                    # 模型编了个不存在的工具
            _record(scratchpad, trace,
                    tool=call["name"], args=call["args"], ok=False,
                    reason="unknown_tool",
                    observation=f"There is no tool called {call['name']!r}.")
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
                _record(scratchpad, trace,
                        tool=spec.name, args=call["args"], ok=False,
                        reason="already_known",
                        observation=(
                            f"You already checked that this turn. The answer was: "
                            f"{previous['observation']} Act on it instead of looking again."
                        ))
                continue

        # 每轮调用次数上限：护栏本身也是数据驱动的，循环只数次数，
        # 不需要知道"发信"或"查记忆"各自该限几次。没有它，模型可能
        # 一轮连发四封信，步数耗尽却什么正事都没做。
        if spec.max_per_turn:
            used = sum(1 for entry in scratchpad if entry["tool"] == spec.name and entry["ok"])
            if used >= spec.max_per_turn:
                _record(scratchpad, trace,
                        tool=spec.name, args=call["args"], ok=False,
                        reason="rate_limited",
                        observation=(
                            f"You have already used {spec.name} {used} time(s) this turn. "
                            f"Do something else now."
                        ))
                continue

        # ── 做：交给工具自己的 handler，锁外执行（查询类不碰共享状态）──
        result = spec.handler(agent, call["args"], world)

        # ── 提交：行动类成功了才进锁，并对照最新世界重新裁决一次 ──
        if result["ok"] and spec.terminal:
            result = with_world(lambda current: _commit(agent, spec, call["args"], current))
            if result["ok"]:
                _clip_to_next_deadline(agent, result, world)

        _record(scratchpad, trace,
                tool=spec.name, args=call["args"], ok=result["ok"],
                reason=result.get("reason"), observation=result["observation"],
                terminal=spec.terminal)

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


def _clip_to_next_deadline(agent, result, world):
    """不让一个动作睡过约定。

    ``sleep`` 能跑九个小时，普通动作也能到三小时。而动作一旦开始，后端就
    退出了——播放期间没人会再问它任何事，所以"到时候提醒他"根本无从发生。

    唯一能管住的时刻，就是**定下时长的这一刻**。这不是中断：没有任何东西
    把他叫醒，只是这个动作一开始就不允许有那么长。

    在约定时刻之前留一段余量，因为赶路要时间——四点整醒来是走不到公园的。
    """
    from world.goals import COMMITMENT_BUFFER_MINUTES, goal_store
    from world.locations import MIN_ACTION_MINUTES

    decision = result.get("decision")
    if not decision:
        return

    deadline = goal_store.next_deadline(agent.name, world.life_day)
    if deadline is None:
        return

    latest_end = deadline - COMMITMENT_BUFFER_MINUTES
    available = latest_end - world.time_minutes
    planned = int(decision["duration_minutes"])
    if available >= planned:
        return                                  # 本来就赶得上，不动它

    clipped = max(MIN_ACTION_MINUTES, available)
    if clipped >= planned:
        return

    decision["duration_minutes"] = clipped
    # 说明为什么变短了，否则模型下一轮会困惑于"我明明打算做三小时"。
    from world.clock import format_clock

    result["observation"] += (
        f" You cut it short to {clipped} minutes — you are due somewhere "
        f"by {format_clock(deadline)}."
    )


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
