"""消融：关掉一个能力再跑同一道题，看任务达成率掉多少。

这是整个评估集里最值钱的一块——**用数字回答"你这次改造带来了什么"**，
而不是"感觉更合理了"。基线自己跑出 80% 说明不了什么；基线 80%、关掉
某个能力掉到 20%，那个能力才算被证明有用。

挑消融项的标准是**信息量**，不是覆盖率。比如"把 check_inbox 也摘掉"看着
很彻底，但那三道题的起因都在信箱里——摘了必然零分，跑它只是烧钱确认
"看不见任务就做不成任务"。所以 `no-outgoing-mail` 只摘 `send_mail`：
请求照样收得到，但没法开口借钱、没法商量，考的是**异步通信对协作的贡献**。

## ⚠️ `single-step` 不是「改造前」，`pre-rebuild` 才是

这两条差一件事，而那件事恰恰是改造的另一半：

    single-step   十四件工具可选，但只准想一步
    pre-rebuild   只准想一步，而且**只有 move_to** —— 改造前的真实形态

改造前模型是被 ``tool_choice: {"name": "move_to"}`` 摁着填一张表的，
所以它每轮必定产出一个动作。而 `single-step` 给了它选择权却不给第二步，
于是它一旦挑了 `check_inbox` 这一轮就作废了——首跑里 `single-step` 的
空转轮次高达 18-21%（基线 5-7%），改变世界的动作 0 个。

**拿 `single-step` 冒充改造前是稻草人**：它比改造前更差，而差的那部分
不是改造带来的。要讲"这次改造带来了什么"，对照组只能是 `pre-rebuild`。

顺带一个读表时的坑：**单步的两条消融，「无效调用率」必然是 0**。
不是它们更准，是 `already_known` / `rate_limited` 天生需要前一步存在。
"""

from dataclasses import dataclass

from tools import TOOL_REGISTRY


@dataclass(frozen=True)
class Ablation:
    name: str
    headline: str
    tools_disabled: tuple = ()
    max_steps: int = None
    filter_tools: bool = False
    omit_context: tuple = ()
    handover_windows: bool = True


def _everything_except(*keep):
    """从**真注册表**里减，不手写清单。

    手写的话，以后往注册表里加一件工具，这个消融就会悄悄把它留下——
    而"改造前"多了一件工具，对照就不成立了，还没有任何东西会报错。
    """
    missing = set(keep) - set(TOOL_REGISTRY)
    assert not missing, f"想保留的工具不存在：{sorted(missing)}"
    return tuple(sorted(set(TOOL_REGISTRY) - set(keep)))


ABLATION_REGISTRY = {
    "none": Ablation(
        name="none",
        headline="完整能力（基线）",
    ),
    "single-step": Ablation(
        name="single-step",
        headline="有十四件工具可选，但每轮只准想一步",
        max_steps=1,
    ),
    "pre-rebuild": Ablation(
        name="pre-rebuild",
        headline="只准想一步 + 只有 move_to —— 真正的改造前形态",
        tools_disabled=_everything_except("move_to"),
        max_steps=1,
    ),
    "no-outgoing-mail": Ablation(
        name="no-outgoing-mail",
        headline="收得到信，发不出信 —— 没法开口借钱、没法商量",
        tools_disabled=("send_mail",),
    ),
    "no-meetings": Ablation(
        name="no-meetings",
        headline="不能约时间地点，只能靠走过去碰运气",
        tools_disabled=("accept_meeting",),
    ),
    "no-tasks": Ablation(
        name="no-tasks",
        headline="没有跨轮的记事本，全靠上下文里记得住",
        tools_disabled=("accept_task",),
    ),
    "state-filtered-tools": Ablation(
        name="state-filtered-tools",
        headline="此刻用不了的工具不进 schema，只在上下文里留一行",
        filter_tools=True,
    ),
    "no-events": Ablation(
        name="no-events",
        headline="不告诉他上次行动之后发生了什么（钱到账、东西到手）",
        omit_context=("what_has_happened_since",),
    ),
    "no-handover-window": Ablation(
        name="no-handover-window",
        headline="人就在眼前、东西在手上——不提醒他这一刻交得出去",
        # 摘的是**三行字**，不是一件工具：`give_item` 照样在，照样能调。
        # 考的是"上下文把两条已知信息拼在一起"值多少——改之前它们分三段
        # 摆着，模型 302 轮里一次都没连起来过。
        handover_windows=False,
    ),
    "no-town-knowledge": Ablation(
        name="no-town-knowledge",
        headline="不告诉他营业时间、容量、谁开哪家店，以及镇上的规矩",
        # 这一段是**补失忆**，不是给情报：世界一直知道药房六点关门，居民
        # 却只在撞上关门之后才被告知。整轮评估 `closed` 撞了 377 次，占全部
        # 驳回的 15%。加了它就得能量出它值多少，否则又是一次"感觉更合理了"。
        omit_context=("what_this_town_is_like",),
    ),
    "no-prices": Ablation(
        name="no-prices",
        headline="不告诉他任务里那样东西多少钱",
        omit_context=("what_things_cost",),
    ),
    "no-recall": Ablation(
        name="no-recall",
        headline="不能主动检索记忆",
        tools_disabled=("recall",),
    ),
}


def get_ablation(name):
    return ABLATION_REGISTRY.get(name)
