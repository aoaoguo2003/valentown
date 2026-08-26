"""应用装配的冒烟测试。

两百多个测试全绿，而 ``main.py`` 却因为 import 一个不存在的名字而根本加载
不了——没有一个测试碰过它。单元测试覆盖的是模块，装配本身也需要被覆盖：
**一个进程起不来的应用，模块测得再全也没有意义。**

这里只做最粗的检查：能不能导入、路由在不在、世界快照能不能真的建出来。
不启动服务器、不发请求、不调 LLM。
"""

import pytest


@pytest.fixture(scope="module")
def app_module(tmp_path_factory, monkeypatch_module):
    """把所有持久化指向临时目录后再导入路由模块。

    ``api/routes.py`` 在导入时就会建 agents、读进度文件、初始化记忆库，
    所以隔离必须发生在 import 之前。
    """
    import agents.state as agent_state
    import world.economy as economy_module
    import world.goals as goals_module
    import world.mailbox as mailbox_module

    # ⚠️ 用 monkeypatch 而不是直接赋值：直接赋值改的是**模块全局**，
    # 这个模块跑完之后它还留在那儿，后面所有测试看到的都是沙盒路径。
    # test_layout.py 里那个"存档是不是还在 backend/ 根下"的测试，
    # 就是被这一手弄红的。
    sandbox = tmp_path_factory.mktemp("app")
    monkeypatch_module.setattr(agent_state, "STATE_DIR", sandbox / "states")
    monkeypatch_module.setattr(
        economy_module, "economy", economy_module.Economy(path=sandbox / "economy.json"))
    monkeypatch_module.setattr(
        mailbox_module, "mailbox", mailbox_module.Mailbox(path=sandbox / "mail.json"))
    monkeypatch_module.setattr(
        goals_module, "goal_store", goals_module.GoalStore(path=sandbox / "goals.json"))

    import api.routes as routes
    return routes


@pytest.fixture(scope="module")
def monkeypatch_module():
    from _pytest.monkeypatch import MonkeyPatch

    patch = MonkeyPatch()
    yield patch
    patch.undo()


def test_the_app_actually_imports(app_module):
    """曾经 main.py 从 world 导入了一个拼写不存在的名字，两百多个测试全绿。"""
    assert app_module.app is not None
    assert len(app_module.agents) == 7


def test_the_launcher_still_reaches_the_app(app_module):
    """``scripts/start_backend.cmd`` 跑的是 main.py，不是 api/routes.py。

    路由搬进 api/ 之后，入口那一层同样可能断——而它断了，测试全绿也没用。
    """
    import main

    assert main.app is app_module.app


def test_every_route_the_frontend_calls_is_registered(app_module):
    """前端依赖这些 URL，改名就是破坏契约。"""
    rules = {rule.rule for rule in app_module.app.url_map.iter_rules()}
    for path in [
        "/decide_next_action",
        "/complete_agent_action",
        "/generate_conversation",
        "/start_new_day",
        "/get_config",
        "/get_simulation_progress",
        "/update_simulation_progress",
        "/get_agent_internal_states",
        "/get_agent_memories",
        "/get_conversations",
    ]:
        assert path in rules, path


def test_the_world_provider_builds_a_complete_snapshot(app_module):
    """路由层交给决策循环的那个 with_world，必须真能建出完整快照。

    这是漏掉 holdings 那次事故的正面覆盖：快照少一个字段，任务判定会静默
    失效，而日志里只会显示"模型没做到"。
    """
    with_world = app_module.make_world_provider("2:00 PM", 1)
    world = with_world(lambda current: current)

    assert world.time_minutes == 14 * 60
    assert world.life_day == 1
    assert set(world.agent_locations) == {agent.name for agent in app_module.agents}
    # 四个状态模块的东西一样都不能少。
    for probe in ("balances", "holdings", "unread_counts"):
        assert hasattr(world, probe)
    assert world.weather_code is not None
    assert world.balance_for("Ron Parker") >= 0
    assert isinstance(world.holdings_for("Ron Parker"), dict)


def test_agents_start_where_they_live(app_module):
    for agent in app_module.agents:
        assert agent.current_location.startswith(agent.home_area)
