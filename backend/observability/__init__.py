"""可观测性：这套系统在运行的时候，到底发生了什么。

包里两个模块，方向相反：

    trace.py      **写**。每一次 LLM 调用、每一步工具调用发生的当下，
                  追加一条结构化 JSONL。它在决策的热路径上，所以任何写入
                  失败都被静默吞掉——可观测性绝不能拖垮模拟。

    metrics.py    **读**。把日志还原成一轮一轮的决策，汇总成能横向比较的
                  数字：想了几步、无效调用率、被拒后换不换招。

⚠️ 这里只回答「发生了什么」，不回答「做得好不好」。后者要对着题目才判得了，
归 ``evals/``。这条线是故意划的：``metrics.py`` 因此不需要知道任何场景，
拿一份线上真跑的日志照样能算。

下面 re-export 的是**写**那一侧的接口——决策路径上每个模块都在用它，
所以拆包时保持原样，五处 ``from observability import ...`` 一行都不用改。
``metrics`` 不在这里 import：读日志的工具不该让写日志的热路径多付一分钱，
要用就显式 ``from observability.metrics import summarise``。
"""

from observability.trace import (  # noqa: F401  （re-export，保持拆包前的调用方式）
    current_context,
    log_action_event,
    log_llm_call,
    trace_operation,
)

__all__ = ["current_context", "log_action_event", "log_llm_call", "trace_operation"]
