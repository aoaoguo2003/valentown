"""工具的公共骨架：ToolSpec、执行结果的构造函数、共用参数片段。

最关键的字段是 ``ToolSpec.terminal``：它决定一次工具调用之后，本轮决策
循环要不要收敛。

判据是**这个工具占不占用游戏时间**——换句话说，它回答不回答「接下来这段
时间你在哪、做什么」这个问题：

  * ``terminal=True``（move_to、stay）：占用游戏时间。一轮必须、且只能
    回答一次这个问题——时钟只能往前推一次，前端也只能播一段动画。
  * ``terminal=False``（recall、发信、查库存、查天气）：不占用游戏时间，
    是做出那个决定**之前**的准备动作，因此一轮之内可以连续调用多次。

判据**不能**是「改不改变世界」。发一封信确实改变了世界（对方收件箱多了
一封），但它不占游戏时间；若因此判它 terminal，本轮就会在时钟没有推进的
情况下结束，下一轮立刻又要决策——白白空转一次完整的 HTTP 请求和一次 LLM
调用。反过来说：**不花时间的工具一律 terminal=False**。

另一个字段 ``read_only`` 管的是另一件事：**同一轮里重复问同一个问题有没有
意义**。真跑两天的数据显示模型会反复查同一个货架、同一个余额，有几轮五步
全花在查东西上、一个动作都没做出来。纯查询的答案在一轮之内不会变，所以
第二次同参数调用直接拒绝，并把上次的答案附在拒绝理由里——比让它再查一遍
省一步，也比只说"你查过了"有用。

``buy``、``send_mail``、``transfer`` 这类**不是** read_only：连买两件、
连发两封信都是合法意图，重复调用有实际效果。
"""

from dataclasses import dataclass
from typing import Callable

from world.locations import AGENT_NAMES


@dataclass(frozen=True)
class ToolSpec:
    """一个工具的完整定义：模型看到什么、程序怎么执行、执行完要不要收敛。"""

    name: str
    description: str          # 模型据此决定要不要选这个工具
    parameters: dict          # JSON Schema，直接进 API 的 tools 参数
    handler: Callable         # handler(agent, args, world) -> 执行结果字典
    terminal: bool            # 占用游戏时间吗？占用则本轮收敛，不占则可继续
    max_per_turn: int = 0     # 一轮之内最多调几次；0 表示不限
    read_only: bool = False   # 纯查询吗？纯查询重复问同一件事没有意义
    eligible: Callable = None  # 谁**永远**用得上；None 表示人人可见
    available_now: Callable = None  # 此刻用得上吗？见 unavailable_reason

    def is_eligible(self, agent_name):
        """``agent_name`` 会不会被摆上这件工具。

        ⚠️ 判据是**永久**资格，不是此刻能不能用。店主身份是永久的：
        Emma 走到哪儿都补不了超市的货，让她看见 ``restock`` 只有坏处。

        但"要在店里才能买"这种**临时**门槛不归这一层管，见下面那条。
        """
        return self.eligible is None or bool(self.eligible(agent_name))

    def unavailable_reason(self, agent, world):
        """此刻调它会不会**必被拒**？会的话返回一句人话，否则 None。

        ⚠️ **这不是权限，是省字。**看不见的能力模型不会为它做计划——它只会
        在"当下能做什么"里打转，永远不会为了解锁某个能力而先移动。
        **能力的可见性是规划的前提**，这条没变。

        所以被它摘掉的工具**不从模型眼前消失**：完整 schema 不进请求
        （一件 150–350 tokens），但决策上下文里留一行「buy（要先进店）」
        （约 11 tokens）。能力还看得见，账省了九成。

        起因是量出来的：一次决策 `prompt_tokens` 中位 4279，而真正的决策
        上下文只有约 649——**输入的 85% 是工具 schema**，而且每次一模一样。

        ⚠️ 谓词和 handler 里的检查是**同一件事写了两遍**，走散的后果不对称：
        谓词过严 → 模型看不见一件其实能用的工具（**丢能力**）；
        谓词过松 → 白给一次拒绝（无害）。
        所以**拿不准就返回 None**，并且 `test_tool_filter.py` 拿真 handler 对账。
        """
        if self.available_now is None:
            return None
        return self.available_now(agent, world)

    def to_function_schema(self, agent_name=None):
        """转成 OpenAI 兼容接口要的函数声明。

        ``agent_name`` 用于剔除自我指涉的取值（比如自己不能出现在
        talk_to 的候选里）——取值范围因人而异的部分在这里定制，
        而不是在注册表里为七个居民各存一份 schema。"""
        parameters = self.parameters
        if agent_name and "talk_to" in parameters.get("properties", {}):
            others = [name for name in AGENT_NAMES if name != agent_name]
            parameters = {
                **parameters,
                "properties": {
                    **parameters["properties"],
                    "talk_to": {**parameters["properties"]["talk_to"], "enum": others + ["nobody"]},
                },
            }
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": parameters,
            },
        }


def reject(reason, observation):
    """一次被拒绝的执行。``observation`` 要带足信息量——它会被回灌给
    模型用于重新决策，只说"不行"等于没说。"""
    return {"ok": False, "reason": reason, "observation": observation}


def accept(observation, **payload):
    """一次成功的执行。``payload`` 里携带调用方需要的结构化结果。"""
    return {"ok": True, "reason": None, "observation": observation, **payload}


THOUGHT_FIELD = {
    "type": "string",
    "description": "One short sentence on why you are doing this.",
}
