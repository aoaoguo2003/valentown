

# ---------- read_only 和 cacheable_within_turn 是两件事 ----------

def test_no_tool_claims_to_be_read_only_while_changing_the_world():
    """``check_inbox`` 曾经标着 read_only=True，**而它会把信标成已读**。

    当时没出事只因为 max_per_turn=1 另外挡着；而拦截顺序是 already_known
    先于 rate_limited，也就是说那条缓存分支是真的会走到的。谁哪天把上限
    调到 2，第二次调用就会返回缓存的信、**同时跳过标已读那一步**。
    """
    from tools import TOOL_REGISTRY

    assert TOOL_REGISTRY["check_inbox"].read_only is False, \
        "它调 mailbox.take_unread()，会改变世界"


def test_only_answers_that_stay_put_are_cached():
    """判据是**答案稳不稳**，不是**有没有副作用**。

        货架、信箱   一轮之内会变（七个居民并发决策）  -> 不缓存
        记忆、这一小时的天气   钉死的                  -> 缓存
    """
    from tools import TOOL_REGISTRY

    changes = {"check_stock", "check_inbox"}
    stable = {"recall", "check_weather"}

    for name in changes:
        assert TOOL_REGISTRY[name].cacheable_within_turn is False, f"{name} 会变，不能缓存"
    for name in stable:
        assert TOOL_REGISTRY[name].cacheable_within_turn is True, f"{name} 不会变，该缓存"


def test_nothing_that_changes_the_world_is_ever_cached():
    """缓存一件有副作用的工具 = 悄悄跳过那个副作用。"""
    from tools import TOOL_REGISTRY

    for name, spec in TOOL_REGISTRY.items():
        if spec.cacheable_within_turn:
            assert spec.read_only, f"{name} 有副作用却被缓存了"
