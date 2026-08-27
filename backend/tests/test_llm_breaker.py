"""LLM 的熔断，以及记分卡怎么分辨「模型没做到」和「后端挂了」。

这两件事有同一个来由：一次评估跑到一半 DeepSeek 账户余额见底（HTTP 402），
系统又打了 1927 次注定失败的请求、空转近一小时，最后产出一张三十格
`FAIL / wasted 100%` 的记分卡——**看上去像模型很差，真相是后端没钱了**。

全部用假 response 做故障注入，一次真网络都不打。
"""

import pytest

import llm.client as client_module
from evals.report import _mark, format_comparison, format_scorecard
from llm import LLMClient


class _Response:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


def _ok():
    return _Response(200, {
        "choices": [{"message": {"content": "fine"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
    })


@pytest.fixture(autouse=True)
def reset_breaker():
    """熔断是**类级**的，会跨测试渗漏。每个测试前后都清干净。"""
    LLMClient.clear_fatal_error()
    yield
    LLMClient.clear_fatal_error()


@pytest.fixture(autouse=True)
def no_sleeping(monkeypatch):
    monkeypatch.setattr(client_module.time, "sleep", lambda seconds: None)


@pytest.fixture(autouse=True)
def a_key_that_is_never_used(monkeypatch):
    """给客户端一个假 key。**不发请求，只是让它肯走到发请求那一步。**

    ``_post_with_retries`` 在 ``if not self.api_key`` 时直接 return，于是
    被 monkeypatch 掉的 ``requests.post`` 一次都不会被调到，熔断器也就永远
    不会被触发——六个测试全红，而且红得莫名其妙：

        assert LLMClient.fatal_error is not None
        E       assert None is not None

    在**开发机上看不出来**，因为 ``backend/.env`` 里有真 key；clone 下来
    没有 .env 的人一跑就是六个红，而 README 写着"463 tests, no LLM,
    no network"。这个文件的开头讲的正是"分辨模型没做到 vs 后端挂了"——
    结果它自己栽在了环境上。

    复现：``LLM_API_KEY= DEEPSEEK_API_KEY= python -m pytest tests/ -q``
    """
    monkeypatch.setattr(client_module, "LLM_API_KEY", "test-key-never-sent",
                        raising=False)


def _count_posts(monkeypatch, response_for):
    """替掉 requests.post，记下真正发出去了几次。"""
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(json)
        return response_for(len(calls))

    monkeypatch.setattr(client_module.requests, "post", fake_post)
    return calls


# --- 熔断 --------------------------------------------------------------------

@pytest.mark.parametrize("code", sorted(client_module.FATAL_STATUS_CODES))
def test_an_account_level_failure_trips_the_breaker(monkeypatch, code):
    """401 / 402 / 403 不会自己好：密钥不对、余额没了、权限不够。"""
    calls = _count_posts(monkeypatch, lambda n: _Response(code, text="Insufficient Balance"))
    agent = LLMClient()

    assert agent.get_response("Ron Parker", "hello") is None
    assert LLMClient.fatal_error is not None
    assert str(code) in LLMClient.fatal_error
    # 不该重试——重试一万次也是同一个答案
    assert len(calls) == 1


def test_once_tripped_no_further_request_goes_out(monkeypatch):
    """上一次没有这道闸，代价是 1927 次注定失败的请求。"""
    calls = _count_posts(monkeypatch, lambda n: _Response(402, text="Insufficient Balance"))
    first, second = LLMClient(), LLMClient()

    first.get_response("Ron Parker", "hello")
    assert len(calls) == 1

    # 换一个实例也一样——账户级故障是进程级的，七个居民各持一个客户端，
    # 实例级的熔断等于要各自撞一次墙才生效。
    for _ in range(5):
        assert second.get_response("Emma Harris", "hello") is None
    assert len(calls) == 1, "熔断之后又把请求发出去了"


def test_a_transient_failure_does_not_trip_the_breaker(monkeypatch):
    """503 是临时的，该退避重试，不该拉闸。"""
    _count_posts(monkeypatch, lambda n: _ok() if n >= 2 else _Response(503, text="busy"))
    agent = LLMClient()

    assert agent.get_response("Ron Parker", "hello") == "fine"
    assert LLMClient.fatal_error is None


def test_the_breaker_still_returns_none_rather_than_raising(monkeypatch):
    """线上那条路必须保持「模型不可用就走确定性兜底」，模拟不能卡住。

    停不停是**批量跑的调用方**的决定（读 ``fatal_error``），
    不是客户端替它做主。
    """
    _count_posts(monkeypatch, lambda n: _Response(402, text="no money"))
    agent = LLMClient()

    assert agent.call_tools("Ron Parker", "hi", []) is None      # 不抛异常
    assert agent.get_response("Ron Parker", "hi") is None
    assert agent.rate_importance("Ron Parker", "something", fallback=4) == 4


def test_a_tripped_breaker_still_leaves_a_trace(monkeypatch, tmp_path):
    """否则"这一格为什么全是兜底"在追踪文件里查无对证。"""
    import observability.trace as trace_module

    trace = tmp_path / "llm.jsonl"
    monkeypatch.setattr(trace_module, "LLM_TRACE_FILE", str(trace))
    _count_posts(monkeypatch, lambda n: _Response(402, text="no money"))

    agent = LLMClient()
    agent.get_response("Ron Parker", "hello")     # 拉闸
    agent.get_response("Ron Parker", "hello")     # 熔断后

    from observability import metrics
    statuses = metrics.summarise_cost(metrics.load(trace))["by_status"]
    assert statuses.get("failed") == 1
    assert statuses.get("circuit_open") == 1


# --- 记分卡不能把后端故障说成模型很差 -------------------------------------------

def _row(scenario, ablation, passed, usable, successes, stopped="goal reached"):
    """造一格记分卡结果，只填这两个函数用得到的字段。"""
    return {
        "scenario": scenario, "ablation": ablation, "headline": ablation,
        "passed": passed, "usable": usable, "detail": "", "decisions": 40,
        "stopped_because": stopped, "wall_seconds": 100.0,
        "metrics": {
            "calls": 0 if not successes else 80,
            "invalid_calls": {"rate": 0.0}, "environment_refusals": {"rate": 0.0},
            "replanning": {"rate": None}, "wasted_turns": {"rate": 1.0},
            "world_change": {"turns": 0, "by_tool": {}}, "invented_tools": {},
        },
        "cost": {"calls": 80, "by_status": {"success": successes}},
    }


def test_a_cell_the_backend_broke_shows_as_ERR_not_as_a_failure():
    broken = _row("errand", "none", passed=False, usable=False, successes=0)

    # 断言标记本身，不是搜整张表——图例里就印着 "ERR" 三个字母，
    # 搜全文会永远为真。
    assert _mark(broken) == "ERR"
    assert "ERR" in format_scorecard([broken])


def test_broken_cells_are_kept_out_of_the_comparison_entirely():
    """对照表是最终要拿出去讲的东西。宁可少一行，不能多一行假的。"""
    rows = [
        _row("errand", "none", passed=True, usable=True, successes=80),
        _row("errand", "single-step", passed=False, usable=False, successes=0),
    ]

    comparison = format_comparison(rows)

    assert "single-step" not in comparison
    assert "有 1 格" in comparison and "已剔除" in comparison


def test_a_healthy_failure_still_shows_as_a_failure():
    """别矫枉过正：模型跑通了但没做到，那就是实打实的 ✗。"""
    healthy = _row("errand", "single-step", passed=False, usable=True, successes=80)

    assert _mark(healthy) == " ✗ "


def test_running_out_of_decisions_is_marked_apart_from_really_failing():
    """跑到上限才结束的是**没跑完**，不是做不到。

    真跑里踩出来的：errand 那条链 11:05 约好 12:00 见面、对方 11:20 已经
    动身，评估在 11:30 掐断了。差三十分钟游戏时间，在记分卡上却和
    "一环都没走"长得一模一样。
    """
    timed_out = _row("errand", "none", passed=False, usable=True, successes=80,
                     stopped="decision limit")
    genuinely = _row("errand", "none", passed=False, usable=True, successes=80,
                     stopped="everyone turned in")

    assert _mark(timed_out) == " ✗⏱"
    assert _mark(genuinely) == " ✗ "
