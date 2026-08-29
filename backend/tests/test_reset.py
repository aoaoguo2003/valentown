"""重置：把整座小镇倒回第一天开局。

⚠️ **这个测试真正防的不是"重置能不能跑通"，是"有没有漏清某一份"。**
漏一份比不重置更糟：小镇看上去是新的，而某个人还记着昨天欠谁一件事，
之后的行为就再也解释不了了——而且不会报错。

所以做法是：先往**每一份**存档里写一点东西，重置，再逐一确认它们空了。
往世界里加新的持久化状态时，这里也要跟着加一条。
"""

import pytest


@pytest.fixture(scope="module")
def monkeypatch_module():
    from _pytest.monkeypatch import MonkeyPatch

    patch = MonkeyPatch()
    yield patch
    patch.undo()


@pytest.fixture(scope="module")
def routes(tmp_path_factory, monkeypatch_module):
    """所有持久化指向临时目录之后再导入路由模块。

    ⚠️ 用 monkeypatch 而不是直接赋值：直接赋值改的是模块全局，跑完还留着，
    后面所有测试看到的都会是沙盒路径。
    """
    import agents.state as agent_state
    import world.economy as economy_module
    import world.goals as goals_module
    import world.mailbox as mailbox_module
    from memory.persona_store import persona_store

    sandbox = tmp_path_factory.mktemp("reset")
    monkeypatch_module.setattr(agent_state, "STATE_DIR", sandbox / "states")
    monkeypatch_module.setattr(
        economy_module, "economy", economy_module.Economy(path=sandbox / "economy.json"))
    monkeypatch_module.setattr(
        mailbox_module, "mailbox", mailbox_module.Mailbox(path=sandbox / "mail.json"))
    monkeypatch_module.setattr(
        goals_module, "goal_store", goals_module.GoalStore(path=sandbox / "goals.json"))
    monkeypatch_module.setattr(persona_store, "persona_dir", sandbox / "personas")

    import api.routes as module
    monkeypatch_module.setattr(module, "PROGRESS_FILE", sandbox / "progress.json")
    monkeypatch_module.setattr(module, "CONVERSATIONS_FILE", sandbox / "conversations.json")
    monkeypatch_module.setattr(module.memory_system, "memory_dir", sandbox / "memories")
    (sandbox / "memories").mkdir(parents=True, exist_ok=True)
    return module


@pytest.fixture
def client(routes):
    routes.app.config["TESTING"] = True
    return routes.app.test_client()


def _dirty_everything(routes):
    """往每一份存档里留下痕迹，好让"漏清了哪一份"暴露出来。"""
    from world.goals import DELIVER

    routes.economy.seed(balances={"Emma Harris": 42},
                        holdings={"Emma Harris": {"cold_medicine": 1}})
    routes.mailbox.send("Gavin Harris", "Emma Harris", "hello", "Adam has a fever",
                        life_day=1, time_text="6:30 AM")
    routes.goal_store.accept("Emma Harris", DELIVER, "Adam Harris", "cold_medicine",
                             deadline_minute=18 * 60, life_day=1, reason="ill")
    routes.events.event_log.record("money_sent", "Gavin Harris",
                                   visible_to={"Emma Harris"}, amount=5)
    routes.memory_system.add_memory("Emma Harris bought medicine", "action", 7,
                                    agent_name="Emma Harris", life_day=1)
    routes.persona_store.set("Emma Harris", "Emma is dependable.", life_day=1)
    routes.conversations_by_day[2] = [{"with": "Gavin Harris", "text": "about the medicine"}]
    routes.save_simulation_progress({
        "current_life_day": 3,
        "current_time_minutes": 15 * 60,
        "status": "running",
        "agent_locations": {"Emma Harris": "Pharmacy.Boss"},
    })


# --- 安全 -----------------------------------------------------------------

def test_it_refuses_without_an_explicit_confirmation(client, routes):
    """⚠️ 这个接口会删数据。重置和查询走同一个 URL，误触一次代价太大——
    所以没有 ``confirm`` 就只回一份"会清掉哪些东西"的清单。"""
    _dirty_everything(routes)

    response = client.post("/reset_simulation", json={})

    assert response.status_code == 400
    body = response.get_json()
    assert body["reset"] is False
    assert body["reason"] == "confirmation_required"
    assert "memories" in body["clears"]
    # 什么都没动
    assert routes.economy.balance("Emma Harris") == 42


def test_an_empty_body_does_not_reset_either(client, routes):
    assert client.post("/reset_simulation").status_code == 400
    assert routes.economy.balance("Emma Harris") == 42


# --- 每一份都要清 -----------------------------------------------------------

def test_it_clears_every_kind_of_saved_state(client, routes):
    _dirty_everything(routes)

    response = client.post("/reset_simulation", json={"confirm": True})

    assert response.status_code == 200
    assert response.get_json()["reset"] is True

    from world.economy import INITIAL_BALANCE

    assert routes.economy.balance("Emma Harris") == INITIAL_BALANCE, "钱包"
    assert routes.economy.holdings("Emma Harris") == {}, "背包"
    assert routes.mailbox.unread_counts().get("Emma Harris", 0) == 0, "信箱"
    assert routes.goal_store.active_for("Emma Harris", 1) == [], "任务"
    assert routes.events.event_log.all() == [], "事件"
    assert routes.memory_system.get_memories("Emma Harris") == [], "记忆"
    assert routes.persona_store.get("Emma Harris") in (None, ""), "人格"
    assert routes.conversations_by_day == {}, "对话"


def test_it_goes_back_to_the_first_morning(client, routes):
    _dirty_everything(routes)

    progress = client.post("/reset_simulation", json={"confirm": True}).get_json()["progress"]

    assert progress["current_life_day"] == 1
    assert progress["current_time_minutes"] == 6 * 60
    assert progress["status"] == "ready"
    # 位置留空：前端按各自的床铺重新摆人，后端不该记着昨天谁睡在哪。
    assert progress["agent_locations"] == {}


def test_needs_go_back_to_their_starting_values(client, routes):
    from agents.state import load_agent_state, save_agent_state

    state = load_agent_state("Emma Harris")
    state["values"]["hunger"] = 3
    save_agent_state("Emma Harris", state)

    client.post("/reset_simulation", json={"confirm": True})

    assert load_agent_state("Emma Harris")["values"]["hunger"] != 3


def test_the_memory_wipe_survives_the_next_save(client, routes):
    """⚠️ 内存和磁盘要**一起**清。这些 store 是进程级单例——只删文件的话，
    下一次落盘会把内存里那份旧记忆原样写回去，看上去重置成功了，转头又全回来。"""
    routes.memory_system.add_memory("something from yesterday", "action", 5,
                                    agent_name="Emma Harris", life_day=1)

    client.post("/reset_simulation", json={"confirm": True})
    routes.memory_system.set_life_day(1, routes.agent_names)   # 逼它落一次盘

    assert routes.memory_system.get_memories("Emma Harris") == []


def test_resetting_twice_is_harmless(client, routes):
    assert client.post("/reset_simulation", json={"confirm": True}).status_code == 200
    assert client.post("/reset_simulation", json={"confirm": True}).status_code == 200


def test_a_drained_account_stops_blocking_a_fresh_start(client, routes):
    """熔断是**进程级**的。重新开局理应把它松开，否则充完值还得重启后端。"""
    from llm import LLMClient

    LLMClient.fatal_error = "status 402: Insufficient Balance"
    try:
        client.post("/reset_simulation", json={"confirm": True})
        assert LLMClient.fatal_error is None
    finally:
        LLMClient.clear_fatal_error()
