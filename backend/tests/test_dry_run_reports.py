"""`dry_run.py` 收尾那段报告的装配测试。

和 ``test_app.py`` 同一类：**单元测试覆盖模块，装配本身也得被覆盖。**

真出过一次事：那行少套了一层 ``summarise``，
``format_report(load(...))`` 把一个 list 喂给了要 dict 的函数。它不在导入时
报错，而是等**整整一次三天跑结束、二十四分钟之后**才抛 TypeError——仿真
数据全都好好的，只有报告打不出来。一次 LLM 驱动的真跑不可能进 CI，所以
这里拿一份手写的两行日志替它把装配走一遍。
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent.parent / "scripts"


@pytest.fixture(scope="module")
def dry_run():
    """按路径加载 ``scripts/dry_run.py``——它不是包的一部分。

    导入它会顺带设 LLM_TRACE_FILE / ACTION_TRACE_FILE 两个环境变量并建
    logs 目录（那是它必须赶在 config 之前做的事），所以这里先存后还。
    """
    import os

    saved = {k: os.environ.get(k) for k in ("LLM_TRACE_FILE", "ACTION_TRACE_FILE")}
    spec = importlib.util.spec_from_file_location("_dry_run", SCRIPTS / "dry_run.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["_dry_run"] = module
    spec.loader.exec_module(module)
    yield module
    for key, value in saved.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    sys.modules.pop("_dry_run", None)


def _write(path, rows):
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                    encoding="utf-8")
    return path


def test_the_two_reports_render_from_real_log_shapes(dry_run, tmp_path):
    """**这条就是那次崩溃。**两份日志形状不同，各自要套对自己的 summarise。"""
    action = _write(tmp_path / "action.jsonl", [
        {"agent_name": "Emma Harris", "life_day": 1, "time_text": "9:20 AM",
         "trace_id": "t1", "step": 0, "terminal": None, "tool": "buy",
         "summary": "item='cold_medicine'", "ok": False,
         "reason": "insufficient_funds", "observation": "You are 5 short."},
        {"agent_name": "Emma Harris", "life_day": 1, "time_text": "9:20 AM",
         "trace_id": "t1", "step": 1, "terminal": True, "tool": "stay",
         "summary": "duration_minutes=30", "ok": True, "observation": "You stay."},
    ])
    llm = _write(tmp_path / "llm.jsonl", [
        # call_kind 是 summarise_cost 用来认「这是一次真调用」的字段，
        # 少了它整份日志会被当成空的——所以这条记录照真实形状写。
        {"ts": "2026-08-27T09:20:00", "trace_id": "t1", "operation": "decision",
         "agent_name": "Emma Harris", "call_kind": "tool",
         "model": "deepseek-v4-flash", "status": "success", "http_status": 200,
         "attempts": 1, "latency_ms": 2100,
         "prompt_tokens": 4000, "completion_tokens": 120, "total_tokens": 4120},
    ])

    text = dry_run.reports(action, llm)

    assert "behaviour" in text and "cost" in text
    assert "turns 1" in text, "行为那半要的是 summarise 的结果，不是原始记录"
    assert "4120" in text or "4,120" in text, "成本那半要真的算出 token"


def test_empty_logs_do_not_blow_up_the_tail(dry_run, tmp_path):
    """跑崩在第一步时两份日志可能是空的。收尾报告不该在这时候再炸一次,
    把真正的失败原因盖掉。"""
    text = dry_run.reports(_write(tmp_path / "a.jsonl", []),
                           _write(tmp_path / "l.jsonl", []))

    assert isinstance(text, str)
