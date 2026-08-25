"""决策循环的单元测试：多工具选择、observation 回灌、提交前重校验，
以及三个出口（行动类成功 / 步数用完 / LLM 不可用）。

用脚本化的假 LLM 代替真实调用：每个测试预先排好模型会依次选哪些工具，
从而能确定性地断言循环的行为。
"""

import threading

from agents.agent import RonParker
from memory.memory_system import MemorySystem
from runtime import MAX_STEPS, run_decision_loop
from world import World


def _make_agent(tmp_path):
    memory = MemorySystem(retention_days=15, memory_dir=tmp_path)
    memory.initialize_agents(["Ron Parker"])
    return RonParker(memory, "Ron_home.Living_room")


def _scripted_llm(agent, monkeypatch, calls):
    """按脚本依次返回工具调用，并记录每次看到的 context，
    以便断言回灌内容真的进了 prompt。"""
    contexts = []
    queue = list(calls)

    def fake_call_tools(agent_name, context, tool_schemas):
        contexts.append(context)
        return queue.pop(0) if queue else None

    monkeypatch.setattr(agent.llm, "call_tools", fake_call_tools)
    return contexts


def _move(destination, action="do something", talk_to="nobody", thought="because"):
    return {
        "name": "move_to",
        "args": {
            "thought": thought,
            "action": action,
            "destination": destination,
            "duration_minutes": 60,
            "talk_to": talk_to,
        },
    }


def _recall(query="something"):
    return {"name": "recall", "args": {"thought": "let me think", "query": query}}


def _world_provider(*snapshots, time_minutes=14 * 60):
    """每次进锁给出一个世界快照；传多个就依次使用，模拟世界在
    思考期间发生变化。锁在这里是真的加的，验证循环没有嵌套持锁。"""
    lock = threading.Lock()
    states = list(snapshots) or [{}]

    def with_world(fn):
        with lock:
            locations = states.pop(0) if len(states) > 1 else states[0]
            return fn(World(time_minutes=time_minutes, agent_locations=locations))

    return with_world


def _run(agent, with_world, triggers=None, time_text="2:00 PM"):
    return run_decision_loop(
        agent,
        internal_state={"values": {"hunger": 40, "energy": 70, "social": 60}},
        triggers=triggers or [],
        day_number=1,
        time_text=time_text,
        current_location="Ron_home.Living_room",
        last_action="had lunch at home",
        with_world=with_world,
    )


# ---------- 出口 ①：行动类工具成功即收敛 ----------

def test_terminal_tool_success_ends_the_turn(tmp_path, monkeypatch):
    agent = _make_agent(tmp_path)
    _scripted_llm(agent, monkeypatch, [_move("Park.Bench", action="read on the bench")])

    decision, steps = _run(agent, _world_provider({}))

    assert decision["destination"] == "Park.Bench"
    assert decision["source"] == "llm"
    assert len(steps) == 1
    assert steps[0]["tool"] == "move_to"
    assert steps[0]["ok"] is True
    assert agent.current_location == "Park.Bench"
    assert agent.last_observation                       # 跨轮回灌用得上


def test_query_tool_does_not_end_the_turn(tmp_path, monkeypatch):
    # recall 是查询类：成功也不收敛，模型拿着回忆继续决定去哪。
    agent = _make_agent(tmp_path)
    agent.memory.add_memory("Ron Parker: played chess with Arthur", "action", 6,
                            agent_name="Ron Parker", life_day=1)
    _scripted_llm(agent, monkeypatch, [_recall("chess"), _move("Park.Chair")])

    decision, steps = _run(agent, _world_provider({}))

    assert [entry["tool"] for entry in steps] == ["recall", "move_to"]
    assert steps[0]["ok"] is True                       # 查成功了
    assert decision["destination"] == "Park.Chair"      # 但要等行动类工具才收敛


def test_recall_result_is_fed_back_into_the_next_prompt(tmp_path, monkeypatch):
    agent = _make_agent(tmp_path)
    agent.memory.add_memory("Ron Parker: promised Ella to buy apples", "action", 7,
                            agent_name="Ron Parker", life_day=1)
    contexts = _scripted_llm(agent, monkeypatch, [_recall("apples"), _move("Supermarket.Fruit_shelf")])

    _run(agent, _world_provider({}))

    assert len(contexts) == 2
    # 成功的查询进"已经知道的"，不和被拒的混在一起。
    assert "What you have found out this turn" in contexts[1]
    assert "promised Ella to buy apples" in contexts[1]


# ---------- 回灌：被拒绝之后带着理由重来 ----------

def test_rejected_action_is_retried_with_the_reason_in_context(tmp_path, monkeypatch):
    agent = _make_agent(tmp_path)
    # 晚上八点先去药房（已打烊，被拒），再改去公园（全天开放，通过）。
    contexts = _scripted_llm(agent, monkeypatch, [
        _move("Pharmacy.Medicine_shelf", action="buy medicine"),
        _move("Park.Bench", action="take a walk"),
    ])

    decision, steps = _run(agent, _world_provider({}, time_minutes=20 * 60), time_text="8:00 PM")

    assert len(steps) == 2
    assert steps[0]["ok"] is False
    assert steps[0]["reason"] == "closed"
    assert decision["destination"] == "Park.Bench"
    # 第二次决策的 prompt 里必须带着第一次的拒绝理由，而且被拒的要单独成段——
    # 混在成功结果里的话，"这条路走不通"和"我刚知道的事实"长得一模一样。
    assert "Pharmacy is closed" in contexts[1]
    assert "What the town refused this turn" in contexts[1]
    assert "work around the refusals" in contexts[1]


def test_unknown_tool_is_rejected_and_the_loop_continues(tmp_path, monkeypatch):
    agent = _make_agent(tmp_path)
    _scripted_llm(agent, monkeypatch, [
        {"name": "teleport", "args": {"thought": "worth a try"}},   # 模型编的
        _move("Park.Bench"),
    ])

    decision, steps = _run(agent, _world_provider({}))

    assert steps[0]["reason"] == "unknown_tool"
    assert steps[0]["ok"] is False
    assert decision["destination"] == "Park.Bench"


# ---------- 提交前重校验：决策快照会过期 ----------

def test_seat_taken_during_thinking_forces_a_replan(tmp_path, monkeypatch):
    agent = _make_agent(tmp_path)
    # 第一次快照：咖啡馆还有空位，模型据此决定去咖啡馆。
    # 提交时的快照：三个顾客已经坐满——决策依据的世界已经过期。
    empty_cafe = {}
    full_cafe = {
        "Mia Thompson": "Café_bar.Counter",
        "Arthur Morgan": "Café_bar.Window_seat",
        "Gavin Harris": "Café_bar.Patio",
    }
    contexts = _scripted_llm(agent, monkeypatch, [
        _move("Café_bar.Corner_table", action="have a coffee"),
        _move("Park.Bench", action="sit in the park instead"),
    ])

    decision, steps = _run(agent, _world_provider(empty_cafe, full_cafe, full_cafe))

    assert steps[0]["ok"] is False
    assert steps[0]["reason"] == "full"                 # 提交那一刻才被拒
    assert decision["destination"] == "Park.Bench"
    assert "full" in contexts[1]
    # 被拒的目的地不能被写进世界。
    assert agent.current_location == "Park.Bench"


def test_commit_writes_location_only_on_success(tmp_path, monkeypatch):
    agent = _make_agent(tmp_path)
    start = agent.current_location
    # 模型固执地要去打烊的药房，三次都被拒。
    _scripted_llm(agent, monkeypatch, [_move("Pharmacy.Medicine_shelf")] * MAX_STEPS)

    decision, steps = _run(agent, _world_provider({}, time_minutes=22 * 60), time_text="10:00 PM",
                           triggers=[{"need": "hunger", "reason": "hungry", "intent": "seek_food"}])

    assert agent.current_location != start              # 最终落在兜底目的地
    assert agent.current_location == decision["destination"]


# ---------- 出口 ②③：护栏 ----------

def test_exhausted_steps_fall_back_deterministically(tmp_path, monkeypatch):
    agent = _make_agent(tmp_path)
    _scripted_llm(agent, monkeypatch, [_move("Pharmacy.Medicine_shelf")] * MAX_STEPS)

    decision, steps = _run(agent, _world_provider({}, time_minutes=22 * 60), time_text="10:00 PM",
                           triggers=[{"need": "hunger", "reason": "hungry", "intent": "seek_food"}])

    assert decision["source"] == "fallback"
    assert decision["destination"] == "Ron_home.Kitchen"    # 饿了就回自己厨房
    assert len(steps) == MAX_STEPS
    assert all(entry["reason"] == "closed" for entry in steps)


def test_llm_unavailable_falls_back_immediately(tmp_path, monkeypatch):
    agent = _make_agent(tmp_path)
    calls = {"count": 0}

    def dead_llm(agent_name, context, tool_schemas):
        calls["count"] += 1
        return None

    monkeypatch.setattr(agent.llm, "call_tools", dead_llm)

    decision, steps = _run(agent, _world_provider({}))

    assert decision["source"] == "fallback"
    assert steps == []
    assert calls["count"] == 1                          # 不空转重试


# ---------- 感知：上下文里只出现看得见的人 ----------

def test_context_only_names_agents_in_the_same_area(tmp_path, monkeypatch):
    agent = _make_agent(tmp_path)
    agent.current_location = "Café_bar.Counter"
    contexts = _scripted_llm(agent, monkeypatch, [_move("Café_bar.Patio")])

    _run(agent, _world_provider({
        "Ron Parker": "Café_bar.Counter",
        "Ella Parker": "Café_bar.Window_seat",     # 同区域，看得见
        "Emma Harris": "Park.Bench",               # 别处，看不见
    }))

    assert "Ella Parker" in contexts[0]
    assert "Emma Harris" not in contexts[0]


# ---------- stay 在循环里 ----------

def _stay_call(action="wait for a reply", talk_to="nobody"):
    return {
        "name": "stay",
        "args": {
            "thought": "no reason to move",
            "action": action,
            "duration_minutes": 30,
            "talk_to": talk_to,
        },
    }


def test_stay_ends_the_turn_without_moving(tmp_path, monkeypatch):
    agent = _make_agent(tmp_path)
    agent.current_location = "Café_bar.Counter"
    _scripted_llm(agent, monkeypatch, [_stay_call("nurse my coffee")])

    decision, steps = _run(agent, _world_provider({"Ron Parker": "Café_bar.Counter"}))

    assert decision["destination"] == "Café_bar.Counter"     # 原地
    assert decision["source"] == "llm"
    assert len(steps) == 1
    assert agent.current_location == "Café_bar.Counter"


def test_waiting_is_expressible(tmp_path, monkeypatch):
    # 这正是通信系统需要的能力：做完一件事之后原地等回音。
    agent = _make_agent(tmp_path)
    agent.current_location = "Pharmacy.Waiting_chair"
    _scripted_llm(agent, monkeypatch, [_stay_call("wait for Ella to reply")])

    decision, _ = _run(agent, _world_provider({"Ron Parker": "Pharmacy.Waiting_chair"}))

    assert "wait" in decision["action"].lower()
    assert decision["destination"] == "Pharmacy.Waiting_chair"


def test_stay_refused_after_closing_triggers_a_replan(tmp_path, monkeypatch):
    # 咖啡馆打烊，待不住 -> 带着拒绝理由重新规划，改回家。
    agent = _make_agent(tmp_path)
    agent.current_location = "Café_bar.Counter"
    contexts = _scripted_llm(agent, monkeypatch, [
        _stay_call("keep reading here"),
        _move("Ron_home.Sofa", action="head home for the night"),
    ])

    decision, steps = _run(
        agent,
        _world_provider({"Ron Parker": "Café_bar.Counter"}, time_minutes=23 * 60),
        time_text="11:00 PM",
    )

    assert steps[0]["tool"] == "stay"
    assert steps[0]["reason"] == "closed"
    assert decision["destination"] == "Ron_home.Sofa"
    assert "cannot stay" in contexts[1]


# ---------- 通信在循环里 ----------

def _mail(to="Ella Parker", subject="apples", body="Could you buy apples today?"):
    return {
        "name": "send_mail",
        "args": {"thought": "I should ask", "to": to, "subject": subject, "body": body},
    }


def _inbox():
    return {"name": "check_inbox", "args": {"thought": "anything new?"}}


def test_send_mail_does_not_end_the_turn(tmp_path, monkeypatch):
    # 发信改变了世界（对方收件箱多了一封）却不占游戏时间，所以本轮继续，
    # 模型还要决定"接下来这段时间干什么"。
    from mailbox import Mailbox
    monkeypatch.setattr("mailbox.mailbox", Mailbox(path=tmp_path / "mail.json"))

    agent = _make_agent(tmp_path)
    _scripted_llm(agent, monkeypatch, [_mail(), _stay_call("wait for a reply")])

    decision, steps = _run(agent, _world_provider({}))

    assert [entry["tool"] for entry in steps] == ["send_mail", "stay"]
    assert steps[0]["ok"] is True
    assert decision["action"] == "wait for a reply"      # 收敛在 stay 上


def test_ask_then_wait_is_a_single_turn(tmp_path, monkeypatch):
    # 这正是 stay 存在的理由：发完信原地等，一轮之内走完。
    from mailbox import Mailbox
    box = Mailbox(path=tmp_path / "mail.json")
    monkeypatch.setattr("mailbox.mailbox", box)

    agent = _make_agent(tmp_path)
    agent.current_location = "Pharmacy.Waiting_chair"
    _scripted_llm(agent, monkeypatch, [
        _mail(to="Ella Parker", subject="money", body="Could you lend me ten?"),
        _stay_call("wait here for Ella's reply"),
    ])

    decision, steps = _run(agent, _world_provider({"Ron Parker": "Pharmacy.Waiting_chair"}))

    assert box.unread_counts()["Ella Parker"] == 1        # 信确实送到了
    assert decision["destination"] == "Pharmacy.Waiting_chair"
    assert len(steps) == 2                                # 一次 HTTP 请求里做完


def test_second_letter_in_one_turn_is_rate_limited(tmp_path, monkeypatch):
    # 没有这个护栏，模型可能一轮连发数封，步数耗尽却什么正事都没干。
    from mailbox import Mailbox
    box = Mailbox(path=tmp_path / "mail.json")
    monkeypatch.setattr("mailbox.mailbox", box)

    agent = _make_agent(tmp_path)
    contexts = _scripted_llm(agent, monkeypatch, [
        _mail(to="Ella Parker"),
        _mail(to="Emma Harris"),                          # 第二封，应被拦下
        _move("Park.Bench"),
    ])

    decision, steps = _run(agent, _world_provider({}))

    assert steps[1]["reason"] == "rate_limited"
    assert steps[1]["ok"] is False
    assert box.unread_counts().get("Emma Harris", 0) == 0  # 第二封没送出去
    assert decision["destination"] == "Park.Bench"
    assert "already used send_mail" in contexts[2]        # 理由回灌给了模型


def test_unread_hint_appears_then_clears_within_the_same_turn(tmp_path, monkeypatch):
    # 未读数每一步都重新取：读完之后同一轮的下一步就归零，
    # 模型不会傻乎乎再读一遍。
    from mailbox import Mailbox
    box = Mailbox(path=tmp_path / "mail.json")
    monkeypatch.setattr("mailbox.mailbox", box)
    box.send("Ella Parker", "Ron Parker", "dinner", "Shall we eat at seven?")

    agent = _make_agent(tmp_path)
    contexts = _scripted_llm(agent, monkeypatch, [_inbox(), _move("Ron_home.Dining_table")])

    def with_world(fn):
        # 每次进锁都重新取未读数，模拟 main.py 的真实行为。
        return fn(World(time_minutes=18 * 60, agent_locations={},
                        unread_counts=box.unread_counts()))

    decision, steps = _run(agent, with_world)

    assert "1 unread letter" in contexts[0]              # 第一步：提示在
    assert "unread" not in contexts[1]                   # 第二步：已归零
    assert "Shall we eat at seven?" in steps[0]["observation"]
    assert decision["destination"] == "Ron_home.Dining_table"


def test_letter_content_only_enters_context_through_the_scratchpad(tmp_path, monkeypatch):
    # 正文从不自动进上下文；它是 check_inbox 的 observation，
    # 经由本轮试错记录回灌，下一步才看得到。
    from mailbox import Mailbox
    box = Mailbox(path=tmp_path / "mail.json")
    monkeypatch.setattr("mailbox.mailbox", box)
    box.send("Ella Parker", "Ron Parker", "bridge", "Meet me at the bridge at nine.")

    agent = _make_agent(tmp_path)
    contexts = _scripted_llm(agent, monkeypatch, [_inbox(), _move("Park.Bridge")])

    def with_world(fn):
        return fn(World(time_minutes=8 * 60, agent_locations={},
                        unread_counts=box.unread_counts()))

    _run(agent, with_world)

    assert "bridge at nine" not in contexts[0]           # 读之前看不到内容
    assert "bridge at nine" in contexts[1]               # 读之后经 scratchpad 才有


# ---------- 省步数：真跑两天暴露出来的两处浪费 ----------

def test_repeating_a_query_returns_last_answer_instead_of_asking_again(tmp_path, monkeypatch):
    # 真跑数据：有几轮五步全花在反复查同一个货架、同一个余额上，
    # 一个动作都没做出来。纯查询的答案一轮之内不会变。
    from economy import Economy
    monkeypatch.setattr("economy.economy", Economy(path=tmp_path / "e.json"))

    agent = _make_agent(tmp_path)
    agent.current_location = "Supermarket.Checkout"
    contexts = _scripted_llm(agent, monkeypatch, [
        {"name": "check_stock", "args": {"thought": "what is on the shelf", "shop": "Supermarket"}},
        {"name": "check_stock", "args": {"thought": "let me look again", "shop": "Supermarket"}},
        _move("Park.Bench"),
    ])

    decision, steps = _run(agent, _world_provider({"Ron Parker": "Supermarket.Checkout"}))

    assert steps[0]["ok"] is True
    assert steps[1]["ok"] is False
    assert steps[1]["reason"] == "already_known"
    # 拒绝时把上次的答案还回去——比让它再查一遍省一步，
    # 也比只说"你查过了"有用。
    assert "bread" in steps[1]["observation"]
    assert "Act on it" in steps[1]["observation"]
    assert decision["destination"] == "Park.Bench"


def test_a_different_query_argument_is_not_blocked(tmp_path, monkeypatch):
    from economy import Economy
    monkeypatch.setattr("economy.economy", Economy(path=tmp_path / "e.json"))

    agent = _make_agent(tmp_path)
    agent.current_location = "Supermarket.Checkout"
    _scripted_llm(agent, monkeypatch, [
        {"name": "check_stock", "args": {"thought": "here", "shop": "Supermarket"}},
        {"name": "check_stock", "args": {"thought": "and there", "shop": "Pharmacy"}},
        _move("Park.Bench"),
    ])

    _, steps = _run(agent, _world_provider({"Ron Parker": "Supermarket.Checkout"}))

    assert steps[0]["reason"] != "already_known"
    assert steps[1]["reason"] != "already_known"     # 问的是另一家店，照常放行


def test_acting_twice_is_still_allowed(tmp_path, monkeypatch):
    # read_only 只管纯查询。连买两件、连发两封信都是合法意图，
    # 重复调用有实际效果，不能一并拦掉。
    from economy import Economy
    from tools import get_tool

    store = Economy(path=tmp_path / "e.json")
    store._balances["Ron Parker"] = 100
    monkeypatch.setattr("economy.economy", store)

    assert get_tool("buy").read_only is False
    assert get_tool("send_mail").read_only is False
    assert get_tool("transfer").read_only is False

    agent = _make_agent(tmp_path)
    agent.current_location = "Café_bar.Counter"
    _scripted_llm(agent, monkeypatch, [
        {"name": "buy", "args": {"thought": "one", "item": "coffee"}},
        {"name": "buy", "args": {"thought": "another", "item": "coffee"}},
        _stay_call("drink up"),
    ])

    _, steps = _run(agent, _world_provider({"Ron Parker": "Café_bar.Counter"}))

    assert steps[0]["ok"] is True
    assert steps[1]["ok"] is True                    # 第二杯照买不误
    assert store.holdings("Ron Parker")["coffee"] == 2


def test_empty_mailbox_is_stated_not_omitted(tmp_path):
    # 真跑数据：check_inbox 被调 49 次，48 次空手——因为"没信就不提示"，
    # 模型只能盲查。明说一句就省下那 48 步。
    agent = _make_agent(tmp_path)

    context = agent.build_decision_context(
        internal_state={"values": {}}, triggers=[], day_number=1,
        time_text="9:00 AM", current_location="Ron_home.Living_room",
        unread_letters=0,
    )

    assert "mailbox is empty" in context
    assert "nobody has written" in context


def test_waiting_letters_are_still_announced(tmp_path):
    agent = _make_agent(tmp_path)

    context = agent.build_decision_context(
        internal_state={"values": {}}, triggers=[], day_number=1,
        time_text="9:00 AM", current_location="Ron_home.Living_room",
        unread_letters=3,
    )

    assert "3 unread letters" in context
    assert "mailbox is empty" not in context


# ---------- 追踪完整性：scratchpad 和日志必须逐步对齐 ----------

def test_every_step_reaches_both_the_scratchpad_and_the_trace(tmp_path, monkeypatch):
    """曾经有三个提前 continue 的分支只写 scratchpad 不写日志。

    后果不是"少了几行日志"：被拦下的重复查询、超限的调用、模型编造的工具名
    在追踪文件里完全不存在——而那恰恰是"无效调用率"要统计的东西。一份缺了
    浪费记录的日志，算出来的浪费率必然是零。

    现有的功能测试一个都发现不了这种洞，因为它们只看返回值，不看日志。
    """
    logged = []
    monkeypatch.setattr("runtime.log_action_event", lambda record: logged.append(record))

    from economy import Economy
    monkeypatch.setattr("economy.economy", Economy(path=tmp_path / "e.json"))

    agent = _make_agent(tmp_path)
    agent.current_location = "Supermarket.Checkout"
    _scripted_llm(agent, monkeypatch, [
        {"name": "teleport", "args": {"thought": "worth a try"}},                    # 不存在的工具
        {"name": "check_stock", "args": {"thought": "look", "shop": "Supermarket"}},  # 正常
        {"name": "check_stock", "args": {"thought": "again", "shop": "Supermarket"}}, # 重复 -> 被拦
        _move("Park.Bench"),                                                          # 收敛
    ])

    _, steps = _run(agent, _world_provider({"Ron Parker": "Supermarket.Checkout"}))

    assert [s["reason"] for s in steps] == [
        "unknown_tool", None, "already_known", None]
    # 关键：日志条数与 scratchpad 逐一对应，一步都不能少。
    assert len(logged) == len(steps)
    assert [r["reason"] for r in logged] == [s["reason"] for s in steps]
    assert [r["step"] for r in logged] == list(range(len(steps)))


def test_fallback_is_traced_too(tmp_path, monkeypatch):
    logged = []
    monkeypatch.setattr("runtime.log_action_event", lambda record: logged.append(record))

    agent = _make_agent(tmp_path)
    _scripted_llm(agent, monkeypatch, [_move("Pharmacy.Medicine_shelf")] * MAX_STEPS)

    decision, steps = _run(agent, _world_provider({}, time_minutes=22 * 60),
                           time_text="10:00 PM",
                           triggers=[{"need": "hunger", "reason": "hungry", "intent": "seek_food"}])

    assert decision["source"] == "fallback"
    # 五步试错 + 一条兜底记录，日志里一条都不少。
    assert len(logged) == len(steps) + 1
    assert logged[-1]["reason"] == "max_steps_exhausted"


def test_facts_and_walls_are_kept_apart(tmp_path, monkeypatch):
    """成功和失败混成一锅时，模型分不清"我已经知道了"和"此路不通"。

    三天真跑里出现了 83 次同一轮内重复提问——它把刚查到的答案当成了
    又一条待办，而不是已知的事实。
    """
    from economy import Economy
    monkeypatch.setattr("economy.economy", Economy(path=tmp_path / "e.json"))

    agent = _make_agent(tmp_path)
    agent.current_location = "Supermarket.Checkout"
    contexts = _scripted_llm(agent, monkeypatch, [
        {"name": "check_stock", "args": {"thought": "look", "shop": "Supermarket"}},
        _move("Pharmacy.Medicine_shelf"),          # 20:00 药房已打烊 -> 被拒
        _move("Park.Bench"),
    ])

    _run(agent, _world_provider({"Ron Parker": "Supermarket.Checkout"},
                                time_minutes=20 * 60), time_text="8:00 PM")

    final = contexts[2]
    facts = final.index("What you have found out this turn")
    walls = final.index("What the town refused this turn")
    assert facts < walls                            # 先摆已知，再摆碰壁
    assert "bread" in final[facts:walls]            # 货架信息归入已知
    assert "Pharmacy is closed" in final[walls:]    # 拒绝理由归入碰壁


def test_pockets_are_visible_without_asking(tmp_path):
    # check_balance 已经删掉：钱和随身物品是"关于自己的、不用动作就知道的"。
    from tools import TOOL_REGISTRY

    assert "check_balance" not in TOOL_REGISTRY

    agent = _make_agent(tmp_path)
    context = agent.build_decision_context(
        internal_state={"values": {}}, triggers=[], day_number=1,
        time_text="9:00 AM", current_location="Ron_home.Living_room",
        balance=12, holdings={"cold_medicine": 1, "bread": 2},
    )

    assert "12 in your purse" in context
    assert "cold_medicine x1" in context
    assert "bread x2" in context


def test_empty_pockets_are_stated_too(tmp_path):
    agent = _make_agent(tmp_path)
    context = agent.build_decision_context(
        internal_state={"values": {}}, triggers=[], day_number=1,
        time_text="9:00 AM", current_location="Ron_home.Living_room",
        balance=3, holdings={},
    )
    assert "carrying nothing" in context
