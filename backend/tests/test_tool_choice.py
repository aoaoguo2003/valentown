"""工具选择用例本身对不对——不跑一次 LLM。

这个文件测的是**出题人**，不是模型：处境摆对了吗、可接受集合写清楚了吗、
理由写了吗。题出错了，后面的分数全是装饰。
"""

import pytest
from evals.tool_choice import ALL_CASES, DISPUTED, UNDISPUTED
from llm import LLMClient
from runtime.scheduler import Town
from tools import TOOL_REGISTRY


@pytest.fixture(autouse=True)
def no_real_llm(monkeypatch):
    monkeypatch.setattr(LLMClient, "call_tools", lambda self, *a, **k: None)
    monkeypatch.setattr(LLMClient, "rate_importance",
                        lambda self, n, t, fallback=4: fallback)


@pytest.mark.parametrize("case", ALL_CASES, ids=lambda c: c.name)
def test_every_acceptable_tool_actually_exists(case):
    """写错一个工具名，这条用例就永远判错——而且不会报错。"""
    unknown = set(case.acceptable) - set(TOOL_REGISTRY)
    assert not unknown, f"{case.name} 的可接受集合里有不存在的工具 {sorted(unknown)}"


@pytest.mark.parametrize("case", ALL_CASES, ids=lambda c: c.name)
def test_every_case_says_what_it_tests_and_why_the_rest_are_wrong(case):
    """写不出"为什么别的不行"，就是还没想清楚这条在考什么。"""
    assert len(case.why.strip()) > 10, f"{case.name} 没说清考什么"
    assert len(case.rejected.strip()) > 10, f"{case.name} 没说清为什么别的不行"


@pytest.mark.parametrize("case", ALL_CASES, ids=lambda c: c.name)
def test_the_acceptable_set_is_neither_empty_nor_everything(case):
    """空集永远判错；全集永远判对。两头都等于没测。"""
    assert case.acceptable, f"{case.name} 可接受集合是空的"
    assert len(case.acceptable) < len(TOOL_REGISTRY), f"{case.name} 什么都收，等于没测"


@pytest.mark.parametrize("case", ALL_CASES, ids=lambda c: c.name)
def test_the_situation_can_actually_be_set_up(case):
    """摆处境的代码本身会不会炸——用假 LLM 走一遍，不花钱。"""
    with Town(days=1) as town:
        agent, internal_state, triggers = case.setup(town)
        assert agent.name
        assert "values" in internal_state
        assert isinstance(triggers, list)


def test_the_disputed_cases_are_kept_separate_from_the_undisputed_ones():
    """哪些边界是人拍板划的，得能一眼看出来。

    将来谁觉得判得不对，**该改的是集合，不是模型**——而要改得动，
    先得知道哪几条是判断、哪几条是事实。
    """
    assert UNDISPUTED and DISPUTED
    assert set(ALL_CASES) == set(UNDISPUTED) | set(DISPUTED)
    assert not (set(UNDISPUTED) & set(DISPUTED))


def test_case_names_are_unique():
    names = [c.name for c in ALL_CASES]
    assert len(names) == len(set(names))
