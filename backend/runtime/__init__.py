"""运行时：驱动一个居民做出下一个动作。

```
agent_runtime.py   决策循环。三个出口，不认识任何具体工具
```

还没长出来、框架里规划的：``scheduler.py``（把 dry_run 的调度提升成正式模块）、
``budgets.py``（token / 调用次数预算）、``context_builder.py``
（现在住在 ``agents/agent.py`` 里）。

这里 re-export 是安全的：没有任何下层模块会反过来 import 运行时。
对比 ``world/__init__.py`` ——那个必须保持空的，因为 ``tools`` 依赖它。
"""

from runtime.agent_runtime import (  # noqa: F401  （re-export，调用方不必知道内部文件名）
    MAX_STEPS,
    run_decision_loop,
)

__all__ = ["MAX_STEPS", "run_decision_loop"]
