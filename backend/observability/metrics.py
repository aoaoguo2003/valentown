"""从动作日志里算出行为指标：这一趟跑下来，居民表现得怎么样。

``trace.py`` 负责**写**——每一步工具调用发生的当下，把它追加进
``action_trace.jsonl``。这个模块负责**读**：把那些散落的行还原成一轮一轮的
决策，再汇总成几个能横向比较的数字。

分工的那条线是：**observability 回答「发生了什么」，evals 回答「做得好不好」**。
所以这里算的全是行为本身——想了几步、被拒了几次、被拒之后换不换招——
它**不需要知道题目是什么**，随便拿一份线上跑出来的日志都能算。
「任务达成没达成」得对着题目才判得了，那个归 ``evals/``。

## 两个必须说清楚的定义

**一轮**（turn）= 一次 ``run_decision_loop``，也就是居民被叫醒一次、从想到
做完的整个过程。日志里每条记录都带 ``step``，``step == 0`` 就是新一轮的开头。

⚠️ **切轮之前必须先按人分组。**七个居民是并发决策的，``log_action_event``
写的是同一个文件，记录天然交错。不分组直接按 step 切，会把两个人的步骤缝
成一轮——第一次算的时候就踩了这个坑：得出"一轮最多 11 步"，按人分组之后
其实是 6 步。

**拒绝分三类**，混在一起算数字就没意义了：

  ① 循环拦下的   编了个不存在的工具名、同一轮重复问、超过每轮上限
  ② 参数填错了   目的地不在白名单、金额是负数、收件人查无此人
  ③ 世界说不行   店关门了、人不在、钱不够、货卖光了

①② 是模型的错，加起来才是**无效调用率**。③ 不是错——那是环境在正常工作，
是模型该据此重新规划的信号。一个健康的跑应该 ①② 很低而 ③ **不为零**：
③ 为零说明这个世界从来没说过"不"，那 ReAct 循环也就没什么可循环的。

用法::

    python -m observability.metrics logs/action_trace.jsonl
"""

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

# --- 工具分类 ---------------------------------------------------------------
#
# 这三个集合和 tools/__init__.py 的注册表是同一件事的两种写法，但这里**故意
# 不 import 注册表**：指标模块要能单独对着一个日志文件跑，包括别的版本产出
# 的、别人机器上拷过来的日志。代价是两处可能走散，所以
# tests/test_metrics.py 里有一个测试专门拿真注册表来对账——走散了测试会红。

TIME_SPENDING = frozenset({"move_to", "stay", "sleep"})
"""占游戏时间的动作。一轮有且只有一个，它就是这一轮的收敛点。"""

LOOKUP = frozenset({"check_inbox", "check_stock", "check_weather", "recall"})
"""纯查询。同一轮里重复问同一件事没有意义，循环会拦。"""

WORLD_CHANGING = frozenset({
    "send_mail", "buy", "restock", "transfer", "give_item",
    "accept_task", "accept_meeting",
})
"""改变了世界却不占游戏时间的动作。居民有没有真的和别人打交道，看的就是它。"""

FALLBACK = "fallback"
"""不是工具，是兜底规则留下的记录：这一轮模型没能自己做出动作。"""

KNOWN_TOOLS = TIME_SPENDING | LOOKUP | WORLD_CHANGING | {FALLBACK}


# --- 拒绝原因分类 -----------------------------------------------------------

GUARD_REASONS = frozenset({
    "unknown_tool",      # 编了个注册表里没有的名字
    "already_known",     # 同一轮里重复问同一件事
    "rate_limited",      # 超过这件工具每轮的次数上限
})
"""① 决策循环自己拦下来的。这些拒绝根本没走到工具的 handler。"""

ARGUMENT_REASONS = frozenset({
    "malformed_arguments", "invalid_destination", "invalid_amount",
    "empty_action", "empty_body", "empty_query", "no_item",
    "unknown_item", "unknown_shop", "unknown_recipient",
    "unknown_person", "unknown_place", "unknown_location",
    "self_addressed", "self_transfer", "self_gift", "self_meeting",
    "bad_deadline", "bad_time", "bad_task", "cannot_arrange",
})
"""② 参数本身就不合法，跟此刻的世界长什么样无关——换个时间再调一样错。"""

ENVIRONMENT_REASONS = frozenset({
    "closed", "full", "target_absent", "insufficient_funds",
    "out_of_stock", "not_in_shop", "not_the_owner", "not_at_home",
    "not_carrying", "shelf_full", "bad_weather", "already_taken",
    "too_many", "deadline_passed", "time_passed",
})
"""③ 参数都对，是此刻的世界不允许。换个时间、换个地点就成了。"""

GIVE_UP_REASONS = frozenset({
    "max_steps_exhausted",   # 想满了步数还没做出动作
    "llm_unavailable",       # 模型压根没应答
    "budget_exhausted",      # 这一天的调用/token 额度用完了
})
"""兜底记录上的理由。**三者要分开**：一个是想不明白，一个是打不通，
一个是没钱了——混成一类，排查时会走冤枉路。"""

KNOWN_REASONS = GUARD_REASONS | ARGUMENT_REASONS | ENVIRONMENT_REASONS | GIVE_UP_REASONS


# --- 读日志 -----------------------------------------------------------------

def load(path):
    """读一个 JSONL 日志（动作的或 LLM 的都行）。

    坏行直接跳过——日志是多线程追加写的，宁可少算一行，也不能因为一行
    被截断就整份报告出不来。

    这里不挑记录类型：``summarise`` 只看带 ``tool`` 的（动作），
    ``summarise_cost`` 只看带 ``call_kind`` 的（LLM 调用）。两种日志本来
    就分开存——字段结构和消费方式都不一样。
    """
    records = []
    path = Path(path)
    if not path.exists():
        return records
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                records.append(record)
    return records


def split_turns(records):
    """把一串记录还原成一轮一轮。

    ⚠️ 先按人分组再按 ``step == 0`` 切。七个居民并发写同一个文件，
    记录是交错的，不分组会把两个人的步骤缝成一轮。

    同一个人的记录之间保持原有先后顺序，所以"被拒之后下一步做了什么"
    这类相邻关系是准的。
    """
    by_agent = defaultdict(list)
    for record in records:
        by_agent[record.get("agent_name")].append(record)

    turns = []
    for agent_records in by_agent.values():
        current = None
        for record in agent_records:
            if record.get("step") == 0 or current is None:
                if current:
                    turns.append(current)
                current = []
            current.append(record)
        if current:
            turns.append(current)
    return turns


# --- 算指标 -----------------------------------------------------------------

def _classify_reason(reason):
    if reason in GUARD_REASONS:
        return "guard"
    if reason in ARGUMENT_REASONS:
        return "arguments"
    if reason in ENVIRONMENT_REASONS:
        return "environment"
    return "unclassified"


def _identity(record):
    """一次调用的身份：工具名 + 参数。用来判断"是不是又撞了同一堵墙"。"""
    return record.get("tool"), record.get("summary")


def summarise(records):
    """把一份动作日志压成一组数字。返回纯 dict，可以直接 json.dumps。"""
    records = [record for record in records if record.get("tool")]
    turns = split_turns(records)
    calls = [r for turn in turns for r in turn if r.get("tool") != FALLBACK]

    steps = [len(turn) for turn in turns]
    convergence = Counter()          # 一轮是怎么结束的
    wasted = Counter()               # 只能靠兜底收场的，按理由分
    guard = Counter()
    arguments = Counter()
    environment = Counter()
    unclassified_reasons = Counter()
    tool_use = Counter()
    invented = Counter()             # 模型凭空编出来的工具名
    changes = Counter()
    turns_with_change = 0
    replanned = repeated = gave_up = 0

    for turn in turns:
        last = turn[-1]
        if last.get("tool") == FALLBACK:
            convergence[FALLBACK] += 1
            wasted[last.get("reason") or "unknown"] += 1
        else:
            convergence[last.get("tool")] += 1

        changed_here = False
        for index, record in enumerate(turn):
            tool = record.get("tool")
            if tool != FALLBACK:
                tool_use[tool] += 1
            if record.get("ok") and tool in WORLD_CHANGING:
                changes[tool] += 1
                changed_here = True

            if record.get("ok"):
                continue

            # 一次拒绝：先归类原因……
            reason = record.get("reason")
            bucket = _classify_reason(reason)
            if bucket == "guard":
                guard[reason] += 1
                # 日志里出现一个注册表没有的名字，有两种可能：模型编的，
                # 或者这个模块的分类落后于代码。``unknown_tool`` 把前者
                # 认了出来，剩下的才该报警——否则每次模型一犯幻觉，
                # 报告底下就多一条假的"分类该补了"。
                if reason == "unknown_tool":
                    invented[tool] += 1
            elif bucket == "arguments":
                arguments[reason] += 1
            elif bucket == "environment":
                environment[reason] += 1
            else:
                unclassified_reasons[reason] += 1

            # ……再看它之后做了什么。三种下场，含义完全不同：
            #   换招   下一步换了工具或换了参数        <- 循环真的在起作用
            #   撞墙   下一步一模一样，又来一遍        <- 拒绝理由没被听懂
            #   没机会 下一步就是兜底，或者根本没有    <- 步数用完了，不怪模型
            following = turn[index + 1] if index + 1 < len(turn) else None
            if following is None or following.get("tool") == FALLBACK:
                gave_up += 1
            elif _identity(following) == _identity(record):
                repeated += 1
            else:
                replanned += 1

        if changed_here:
            turns_with_change += 1

    turn_count = len(turns) or 1
    call_count = len(calls) or 1
    reconsidered = replanned + repeated

    return {
        "turns": len(turns),
        "calls": len(calls),
        "steps_per_turn": {
            "mean": round(sum(steps) / turn_count, 2),
            "max": max(steps) if steps else 0,
        },
        "convergence": dict(convergence.most_common()),
        "wasted_turns": {
            "count": sum(wasted.values()),
            "rate": round(sum(wasted.values()) / turn_count, 4),
            "by_reason": dict(wasted.most_common()),
        },
        "invalid_calls": {
            "count": sum(guard.values()) + sum(arguments.values()),
            "rate": round((sum(guard.values()) + sum(arguments.values())) / call_count, 4),
            "guard": dict(guard.most_common()),
            "arguments": dict(arguments.most_common()),
        },
        "environment_refusals": {
            "count": sum(environment.values()),
            "rate": round(sum(environment.values()) / call_count, 4),
            "by_reason": dict(environment.most_common()),
        },
        "replanning": {
            "replanned": replanned,
            "repeated": repeated,
            "gave_up": gave_up,
            # 分母只算"还有机会再想一步"的那些：步数用完不是模型不肯换招。
            "rate": round(replanned / reconsidered, 4) if reconsidered else None,
        },
        "tool_use": dict(tool_use.most_common()),
        "invented_tools": dict(invented.most_common()),
        "never_used": sorted((TIME_SPENDING | LOOKUP | WORLD_CHANGING) - set(tool_use)),
        "world_change": {
            "turns": turns_with_change,
            "rate": round(turns_with_change / turn_count, 4),
            "by_tool": dict(changes.most_common()),
        },
        "unclassified": {
            # 编出来的名字已经被 unknown_tool 认领了，不算分类漏了。
            "tools": sorted(set(tool_use) - KNOWN_TOOLS - set(invented)),
            "reasons": dict(unclassified_reasons.most_common()),
        },
    }


# --- 成本：读的是另一份日志 ---------------------------------------------------
#
# 行为指标算的是"做得怎么样"，成本算的是"花了多少"。两者来自两份日志：
# 动作日志一步一条，LLM 日志一次请求一条——**一步不等于一次请求**
# （重试会多几次，兜底则一次都不发）。所以分开算，不硬凑成一张表。

def _percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * fraction))]


def summarise_cost(records):
    """把一份 LLM 调用日志压成一组数字：花了多少 token、等了多久、重试几回。"""
    calls = [record for record in records if record.get("call_kind")]
    if not calls:
        return {"calls": 0}

    def total(field):
        return sum(int(call.get(field) or 0) for call in calls)

    latencies = [int(call["latency_ms"]) for call in calls
                 if isinstance(call.get("latency_ms"), int)]
    by_operation = Counter(call.get("operation") or "?" for call in calls)
    by_status = Counter(call.get("status") or "?" for call in calls)
    # attempts=1 是一次就成；大于 1 的部分才是真正多打出去的请求。
    retries = sum(max(0, int(call.get("attempts") or 1) - 1) for call in calls)

    prompt, completion = total("prompt_tokens"), total("completion_tokens")
    return {
        "calls": len(calls),
        "by_operation": dict(by_operation.most_common()),
        "by_status": dict(by_status.most_common()),
        "retries": retries,
        "tokens": {
            "prompt": prompt,
            "completion": completion,
            "total": prompt + completion,
            "per_call": round((prompt + completion) / len(calls), 1),
        },
        "latency_ms": {
            "median": _percentile(latencies, 0.5),
            "p90": _percentile(latencies, 0.9),
            "max": max(latencies) if latencies else None,
        },
    }


def format_cost_report(cost, title=""):
    if not cost.get("calls"):
        return f"=== {title or 'cost'} ===\n  （这份日志里没有 LLM 调用记录）"

    tokens, latency = cost["tokens"], cost["latency_ms"]
    out = [f"=== {title or 'cost'} ===",
           f"  llm calls {cost['calls']}   retries {cost['retries']}",
           f"  tokens    prompt {tokens['prompt']}  completion {tokens['completion']}  "
           f"total {tokens['total']}  ({tokens['per_call']} per call)",
           f"  latency   median {latency['median']}ms  p90 {latency['p90']}ms  "
           f"max {latency['max']}ms",
           f"  by operation {cost['by_operation']}"]
    # 成功率不该埋在字典里——它是这份日志里唯一的健康信号。
    failed = cost["calls"] - cost["by_status"].get("success", 0)
    if failed:
        out.append(f"  ⚠️ 非成功的调用 {failed}  {cost['by_status']}")
    return "\n".join(out)


# --- 出报告 -----------------------------------------------------------------

def _pct(value):
    return "n/a" if value is None else f"{value * 100:.1f}%"


def format_report(summary, title=""):
    """把 summarise 的结果排成一张人看的表。"""
    out = []
    add = out.append

    add(f"=== {title or 'action trace'} ===")
    add(f"  turns {summary['turns']}   tool calls {summary['calls']}   "
        f"steps/turn mean {summary['steps_per_turn']['mean']} max {summary['steps_per_turn']['max']}")

    add("\n  how each turn ended")
    for tool, count in summary["convergence"].items():
        note = "   <- 兜底，模型没能自己做出动作" if tool == FALLBACK else ""
        add(f"    {tool:22s} {count:>5}{note}")

    wasted = summary["wasted_turns"]
    add(f"\n  wasted turns          {wasted['count']:>5}  ({_pct(wasted['rate'])} of turns)")
    for reason, count in wasted["by_reason"].items():
        add(f"    {reason:22s} {count:>5}")

    invalid = summary["invalid_calls"]
    add(f"\n  invalid calls         {invalid['count']:>5}  ({_pct(invalid['rate'])} of calls)"
        f"   <- 模型的错")
    for reason, count in {**invalid["guard"], **invalid["arguments"]}.items():
        add(f"    {reason:22s} {count:>5}")

    refused = summary["environment_refusals"]
    add(f"\n  world said no         {refused['count']:>5}  ({_pct(refused['rate'])} of calls)"
        f"   <- 不是错，是环境在工作")
    for reason, count in refused["by_reason"].items():
        add(f"    {reason:22s} {count:>5}")

    replan = summary["replanning"]
    add(f"\n  after being refused   replanned {replan['replanned']}  "
        f"hit the same wall {replan['repeated']}  no steps left {replan['gave_up']}"
        f"   -> {_pct(replan['rate'])} replanned")

    change = summary["world_change"]
    add(f"\n  turns that changed the world  {change['turns']:>5}  ({_pct(change['rate'])})")
    for tool, count in change["by_tool"].items():
        add(f"    {tool:22s} {count:>5}")

    add("\n  tool use")
    for tool, count in summary["tool_use"].items():
        add(f"    {tool:22s} {count:>5}")
    if summary["never_used"]:
        add(f"    never chosen: {', '.join(summary['never_used'])}")
    if summary["invented_tools"]:
        made_up = ", ".join(f"{name} x{count}" for name, count in summary["invented_tools"].items())
        add(f"    made up out of thin air: {made_up}")

    stray = summary["unclassified"]
    if stray["tools"] or stray["reasons"]:
        add("\n  ⚠️ 分类没跟上代码——metrics.py 的集合该补了")
        if stray["tools"]:
            add(f"    unknown tools  : {', '.join(stray['tools'])}")
        if stray["reasons"]:
            add(f"    unknown reasons: {stray['reasons']}")

    return "\n".join(out)


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    if not argv:
        print(__doc__.strip().splitlines()[-1])
        return 1
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    for path in argv:
        records = load(path)
        name = Path(path).name
        # 一个文件同时喂给两个汇总：它们各挑各的记录类型，
        # 所以动作日志和 LLM 日志都可以直接丢进来。
        if any(record.get("tool") for record in records):
            print(format_report(summarise(records), title=name))
            print()
        if any(record.get("call_kind") for record in records):
            print(format_cost_report(summarise_cost(records), title=name))
            print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
