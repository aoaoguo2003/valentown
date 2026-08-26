"""工具选得对不对：摆好一个处境，只跑一步，看它第一个挑了什么。

和 ``scenarios.py`` 是两种题。场景题跑一整天、看**结果**（药到 Adam 手上没有）；
这里跑**一步**、看**选择**——处境已经把该做什么限死了，它挑对了吗。

一条用例一次 LLM 调用，二十条跑三遍不到 0.3M token，比场景题便宜两个数量级。
所以它适合频繁跑：改了 prompt、改了工具描述、换了模型，跑一遍就知道有没有变差。

## ⚠️ 可接受的是一个**集合**，不是一个答案

「正确的工具」经常不唯一。饿了可以直接走去厨房，也可以先 ``recall`` 想想
昨天在哪吃的——都不算错。所以每条用例给的是 ``acceptable``（一组），
而且**只收唯一答案几乎无争议的处境**。

有争议的宁可不收。收了，量的就是出题人的口味，不是模型的能力——
而一个量口味的指标，比没有指标更糟：它会让人理直气壮地朝错方向优化。

每条用例都必须写清 ``why``（这条考什么）和 ``rejected``（为什么别的不行）。
写不出来的，就是还没想清楚，不该进这个文件。
"""

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class ToolChoiceCase:
    name: str
    why: str                       # 这条考什么
    setup: Callable                # setup(town) -> (agent, internal_state, triggers)
    acceptable: frozenset          # 第一个工具落在这里面就算对
    rejected: str                  # 为什么别的不行——写不出来就是没想清楚
    minute: int = 10 * 60


# --- 摆处境用的小工具 ---------------------------------------------------------

def _find(town, name):
    return next(agent for agent in town.agents if agent.name == name)


def _place(town, **where):
    for name, location in where.items():
        _find(town, name.replace("_", " ")).current_location = location


CALM = {"values": {"hunger": 40, "energy": 75, "social": 60}}
"""需求都不紧急——否则测的是"饿了怎么办"，不是这条用例想问的事。"""


# --- 用例 ---------------------------------------------------------------------

def _unread_mail(town):
    town.mailbox.send(sender="Gavin Harris", recipient="Emma Harris",
                      subject="A favour", body="Could you pick something up today?",
                      life_day=1, time_text="7:00 AM")
    _place(town, Emma_Harris="Emma_home.Living_room")
    return _find(town, "Emma Harris"), CALM, []


def _in_the_shop_ready_to_buy(town):
    town.economy.seed(balances={"Emma Harris": 20})
    town.goals.accept("Emma Harris", "deliver", "Adam Harris", "cold_medicine",
                      18 * 60, 1, "Adam has a fever")
    _place(town, Emma_Harris="Pharmacy.Boss")
    return _find(town, "Emma Harris"), CALM, []


def _person_is_right_here(town):
    town.economy.seed(holdings={"Emma Harris": {"cold_medicine": 1}})
    town.goals.accept("Emma Harris", "deliver", "Adam Harris", "cold_medicine",
                      18 * 60, 1, "Adam has a fever")
    _place(town, Emma_Harris="Park.Bench", Adam_Harris="Park.Tree")
    return _find(town, "Emma Harris"), CALM, []


def _short_of_money_in_the_shop(town):
    town.economy.seed(balances={"Emma Harris": 3})
    town.goals.accept("Emma Harris", "deliver", "Adam Harris", "cold_medicine",
                      18 * 60, 1, "Adam has a fever")
    _place(town, Emma_Harris="Pharmacy.Boss")
    return _find(town, "Emma Harris"), CALM, []


UNDISPUTED = (
    ToolChoiceCase(
        name="unread_mail_at_home",
        why="信就在眼前，读它不占时间也不结束回合。没有先做别的的理由。",
        setup=_unread_mail,
        acceptable=frozenset({"check_inbox"}),
        rejected="别的工具都在没看内容的情况下行动——而内容正是唯一未知的东西。",
    ),
    ToolChoiceCase(
        name="in_the_shop_ready_to_buy",
        why="人在店里、钱够、任务明确。该办事了。",
        setup=_in_the_shop_ready_to_buy,
        # 先查一眼货也完全说得过去——你并不知道人家有没有。所以两个都收。
        acceptable=frozenset({"buy", "check_stock"}),
        rejected="move_to 会离开这家店；send_mail / recall 是站在货架前不办事。",
    ),
    ToolChoiceCase(
        name="person_is_right_here",
        why="东西在手上，收件人就在同一个区域——当面交付的窗口只有此刻。",
        setup=_person_is_right_here,
        acceptable=frozenset({"give_item"}),
        rejected="一走开这个窗口就关了；写信约他更是绕远路——人已经在眼前。",
    ),
    ToolChoiceCase(
        name="short_of_money_in_the_shop",
        why="兜里 3 块，药 8 块，**价格就写在上下文里**。小镇里没有当面要钱的"
            "工具——钱只能由对方 transfer 过来，所以开口的唯一方式是写信。"
            "这正是 errand 卡住的那一步。",
        setup=_short_of_money_in_the_shop,
        acceptable=frozenset({"send_mail"}),
        # ⚠️ 这条第一版是**我出错了**：只给了余额没给价格，她根本不知道要 8 块，
        # 点 buy 其实是合理的探路（拒绝理由会当场告诉她）。我把一个"她不可能
        # 知道"的处境判成了错——正是这个文件开头警告过的"量的是出题人的口味"。
        # 现在价格随任务免费进上下文了，两个数并排摆着，这条才立得住。
        rejected="buy 必被拒——3 < 8 就写在眼前；transfer 是往外给，方向反了"
                 "（真跑里模型犯过这个错）；走去找人也没用，没有当面要钱这件事。",
    ),
)


# --- 有争议的：可接受集合由人定过 -----------------------------------------------
#
# 下面四条的边界不是我一个人划的。每条都列过选项、说明过为什么两边都说得通，
# 由项目负责人拍板。**留个记号：这些集合是判断，不是事实**——将来谁觉得不对，
# 该改的是集合，不是模型。


def _heading_for_the_shop(town):
    town.economy.seed(balances={"Emma Harris": 20})
    town.goals.accept("Emma Harris", "deliver", "Adam Harris", "cold_medicine",
                      18 * 60, 1, "Adam has a fever")
    _place(town, Emma_Harris="Park.Bench")
    return _find(town, "Emma Harris"), CALM, []


def _they_are_not_here(town):
    town.economy.seed(holdings={"Emma Harris": {"cold_medicine": 1}})
    town.goals.accept("Emma Harris", "deliver", "Adam Harris", "cold_medicine",
                      18 * 60, 1, "Adam has a fever")
    _place(town, Emma_Harris="Park.Bench", Adam_Harris="Supermarket.Counter")
    return _find(town, "Emma Harris"), CALM, []


def _nothing_urgent(town):
    _place(town, Mia_Thompson="Mia_home.Living_room")
    return _find(town, "Mia Thompson"), CALM, []


def _meeting_this_afternoon(town):
    town.goals.arrange_meeting("Mia Thompson", "Arthur Morgan", "Park",
                               15 * 60, 1, "agreed to meet")
    _place(town, Mia_Thompson="Mia_home.Living_room")
    return _find(town, "Mia Thompson"), CALM, []


DISPUTED = (
    ToolChoiceCase(
        name="heading_for_the_shop",
        why="任务明确、钱够，但人不在店里。考的是知不知道要先到场。",
        setup=_heading_for_the_shop,
        # 写信问店主有没有货也说得通——check_stock 被拒时系统自己就这么提示：
        # "You could write to Ella Parker and ask"。白跑一趟不如先问。
        acceptable=frozenset({"move_to", "send_mail"}),
        rejected="buy / check_stock 都必被拒——不在店里。站在公园里买不到药。",
    ),
    ToolChoiceCase(
        name="they_are_not_here",
        why="东西在手上，收件人不在同一区域，而且**不知道他在哪**。"
            "这是真跑里的头号拒绝理由 target_absent（三天 44-53 次）。",
        setup=_they_are_not_here,
        # ⚠️ move_to 去碰运气**判为错**，尽管它不一定被拒（人可能真在那儿）。
        # 这条边界是刻意划严的：真跑里模型就是靠走过去碰运气，
        # 一天撞五十次墙，而写信问一句就能解决。
        acceptable=frozenset({"send_mail", "accept_meeting"}),
        rejected="give_item 必被拒；move_to 是碰运气——小镇里没人知道别人在哪，"
                 "唯一可靠的办法是问，或者约。",
    ),
    ToolChoiceCase(
        name="nothing_urgent",
        why="没信、没任务、需求都不紧急。考的是会不会在没事可做时空转。",
        setup=_nothing_urgent,
        # recall 也收：翻翻记忆想想今天该干嘛，说得通。
        acceptable=frozenset({"move_to", "stay", "sleep", "recall"}),
        rejected="check_inbox 上下文已经说了邮箱是空的；check_stock 不在店里；"
                 "买卖转账都无缘无故。",
    ),
    ToolChoiceCase(
        name="meeting_this_afternoon",
        why="下午三点在公园有约，现在上午十点，当前天气晴。"
            "⚠️ **这条是弱测试**：离约定还有五小时，先干别的也完全合理，"
            "所以查预报和推进时间两类都收。它实际能测到的只有一件事——"
            "别去做和这个约定无关的事。",
        setup=_meeting_this_afternoon,
        acceptable=frozenset({"check_weather", "move_to", "stay", "sleep"}),
        rejected="买东西、转账、给东西都和这个约定无关。",
    ),
)

ALL_CASES = UNDISPUTED + DISPUTED


# --- 跑一条 -------------------------------------------------------------------

def run_case(case, *, trace_file=None, llm_trace_file=None):
    """摆好处境，跑**一步**，返回它第一个挑了什么工具。

    ``max_steps=1`` 是关键：一条用例一次 LLM 调用。模型挑了非终止工具时
    这一轮会以兜底收场，但那不影响——我们只看 ``steps[0]``。
    """
    from runtime.agent_runtime import run_decision_loop
    from runtime.scheduler import Town

    with Town(days=1, trace_file=trace_file, llm_trace_file=llm_trace_file) as town:
        agent, internal_state, triggers = case.setup(town)
        _, steps = run_decision_loop(
            agent,
            internal_state=internal_state,
            triggers=triggers,
            day_number=1,
            time_text="10:00 AM",
            current_location=agent.current_location,
            last_action=None,
            with_world=town._make_world_provider(1, case.minute),   # noqa: SLF001
            max_steps=1,
        )

    chose = steps[0]["tool"] if steps else None
    return {
        "case": case.name,
        "chose": chose,
        "acceptable": sorted(case.acceptable),
        "ok": chose in case.acceptable,
        "thought": (steps[0].get("thought") if steps else None),
        "why": case.why,
        "rejected": case.rejected,
    }


def format_tool_choice_report(results):
    out = ["", "=" * 84, "TOOL CHOICE", "=" * 84,
           f"{'case':<30}{'chose':<18}{'acceptable':<26}{'ok':>4}", "-" * 84]
    for r in results:
        out.append(f"{r['case']:<30}{str(r['chose']):<18}"
                   f"{','.join(r['acceptable']):<26}{'✓' if r['ok'] else '✗':>4}")
    hit = sum(1 for r in results if r["ok"])
    out.append("-" * 84)
    out.append(f"  选对 {hit}/{len(results)}")

    misses = [r for r in results if not r["ok"]]
    if misses:
        out.append("")
        out.append("选错的：")
        for r in misses:
            out.append(f"  {r['case']}  挑了 {r['chose']}，可接受的是 {r['acceptable']}")
            out.append(f"    这条考什么：{r['why']}")
            out.append(f"    为什么别的不行：{r['rejected']}")
            if r["thought"]:
                out.append(f"    它当时想的：{r['thought']}")
    return "\n".join(out)


def main(argv=None):
    """`cd backend && python -m evals.tool_choice [--repeats N]`"""
    import argparse
    import json
    import os
    import sys
    from datetime import datetime
    from pathlib import Path

    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=3,
                        help="每条跑几次。模型有温度，一次说明不了什么")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    from config import LLM_API_KEY, LLM_MODEL
    from llm import LLMClient
    if not LLM_API_KEY:
        print("No LLM_API_KEY — set it in backend/.env first.")
        return 1

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = Path(__file__).resolve().parent.parent / "logs" / f"toolchoice_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("LLM_TRACE_FILE", str(out_dir / "llm.jsonl"))

    print(f"model: {LLM_MODEL}   {len(ALL_CASES)} 条 x {args.repeats} 次 "
          f"= {len(ALL_CASES) * args.repeats} 次调用")

    results = []
    for attempt in range(1, args.repeats + 1):
        for case in ALL_CASES:
            results.append({**run_case(
                case,
                trace_file=out_dir / f"{case.name}__{attempt}.jsonl",
                llm_trace_file=out_dir / f"{case.name}__{attempt}.llm.jsonl",
            ), "attempt": attempt})
            mark = "✓" if results[-1]["ok"] else "✗"
            print(f"  {mark} {case.name:<28}#{attempt} -> {results[-1]['chose']}", flush=True)
            if LLMClient.fatal_error:
                print(f"\n!! 中止：{LLMClient.fatal_error}")
                break
        else:
            continue
        break

    print(format_tool_choice_report(results))
    (out_dir / "results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n写到 {out_dir / 'results.json'}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
