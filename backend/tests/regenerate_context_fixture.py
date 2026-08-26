"""重录决策上下文的标尺。

``test_context_builder.py`` 里那个"一字不差"的测试对着
``fixtures/decision_context.json`` 比。它红了有两种可能：

  * 你不小心改了 prompt        -> 撤销
  * 你**有意**改了 prompt      -> 跑这个脚本重录

第二种情况才用得上它。**先看清楚 diff 再重录**——一键抹平的东西，
和没有这个测试是一样的。

    cd backend && python -m tests.regenerate_context_fixture
"""

import json
import tempfile
from pathlib import Path

from agents.agent import EmmaHarris
from memory.memory_system import MemorySystem
from memory.persona_store import persona_store

FIXTURE = Path(__file__).with_name("fixtures") / "decision_context.json"


def main():
    sandbox = Path(tempfile.mkdtemp())
    persona_store.persona_dir = sandbox / "personas"
    memory = MemorySystem(retention_days=15, memory_dir=sandbox / "memories")
    memory.initialize_agents(["Emma Harris"])

    golden = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for name, case in golden.items():
        agent = EmmaHarris(memory, "Emma_home.Living_room")
        if name == "mid_turn":
            agent.last_observation = "Nobody else is here."
        fresh = agent.build_decision_context(**case["kwargs"])
        if fresh != case["expected"]:
            print(f"  {name}: {len(case['expected'])} -> {len(fresh)} 字符")
        case["expected"] = fresh

    FIXTURE.write_text(json.dumps(golden, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"重录完成：{FIXTURE}")


if __name__ == "__main__":
    main()
