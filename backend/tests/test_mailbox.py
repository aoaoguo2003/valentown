"""邮件系统的单元测试：投递、读取、并发写，以及最要紧的两条——
未读**数量**免费进上下文，信的**内容**必须花一步去取；发信人无从得知
对方读没读。不涉及任何 LLM 调用。"""

import threading

import pytest

from agents.agent import RonParker
from world.mailbox import INBOX_LIMIT, Mailbox
from memory.memory_system import MemorySystem
from tools import get_tool
from world.snapshot import World


@pytest.fixture
def box(tmp_path):
    return Mailbox(path=tmp_path / "mailboxes.json")


@pytest.fixture
def agent(tmp_path):
    memory = MemorySystem(retention_days=15, memory_dir=tmp_path / "mem")
    memory.initialize_agents(["Ron Parker"])
    return RonParker(memory, "Ron_home.Living_room")


# ---------- 投递与读取 ----------

def test_letter_lands_in_the_recipient_box(box):
    box.send("Ron Parker", "Ella Parker", "apples", "Could you buy apples today?")

    assert box.unread_counts() == {"Ella Parker": 1}
    letters = box.take_unread("Ella Parker")
    assert len(letters) == 1
    assert letters[0]["from"] == "Ron Parker"
    assert letters[0]["body"] == "Could you buy apples today?"


def test_reading_marks_as_read_so_it_is_not_read_twice(box):
    box.send("Ron Parker", "Ella Parker", "apples", "Could you buy apples?")

    assert len(box.take_unread("Ella Parker")) == 1
    assert box.take_unread("Ella Parker") == []          # 第二次读不到了
    assert box.unread_counts().get("Ella Parker", 0) == 0


def test_sender_gets_no_read_receipt(box):
    # 发信人只知道信送到了，不知道对方何时读、读没读。
    result = box.send("Ron Parker", "Ella Parker", "hi", "Are you free later?")
    assert "read" in result and result["read"] is False
    # 收件人读了之后，发信人这边没有任何可查的回执渠道。
    box.take_unread("Ella Parker")
    assert box.unread_counts().get("Ron Parker", 0) == 0


def test_long_body_is_truncated_not_rejected(box):
    box.send("Ron Parker", "Ella Parker", "x" * 200, "y" * 5000)
    letter = box.take_unread("Ella Parker")[0]
    assert len(letter["subject"]) <= 60
    assert len(letter["body"]) <= 280


def test_pruning_never_drops_unread_letters(box):
    # 收件箱有上限，但被丢弃的只能是已读的旧信。
    for index in range(INBOX_LIMIT + 10):
        box.send("Ron Parker", "Ella Parker", f"note {index}", "read me")
    box.take_unread("Ella Parker")                        # 全部标记已读
    for index in range(5):
        box.send("Ron Parker", "Ella Parker", f"fresh {index}", "unread")

    assert len(box.take_unread("Ella Parker")) == 5        # 未读的一封没丢


def test_persists_across_instances(tmp_path):
    path = tmp_path / "mailboxes.json"
    Mailbox(path=path).send("Ron Parker", "Ella Parker", "hi", "hello there")

    reopened = Mailbox(path=path)
    assert reopened.unread_counts() == {"Ella Parker": 1}


# ---------- 并发：收件箱是跨 agent 的共享可变状态 ----------

def test_concurrent_sends_do_not_lose_letters(box):
    # 六个人同时给同一个人写信：读-改-写若不加锁，就会丢信。
    senders = ["Ron Parker", "Emma Harris", "Gavin Harris",
               "Adam Harris", "Mia Thompson", "Arthur Morgan"]
    barrier = threading.Barrier(len(senders))

    def send(name):
        barrier.wait()                                    # 尽量让写入真正重叠
        for index in range(10):
            box.send(name, "Ella Parker", f"{name} {index}", "hello")

    threads = [threading.Thread(target=send, args=(name,)) for name in senders]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert box.unread_counts()["Ella Parker"] == len(senders) * 10


def test_concurrent_reads_never_deliver_the_same_letter_twice(box):
    for index in range(50):
        box.send("Ron Parker", "Ella Parker", f"note {index}", "hello")

    collected = []
    guard = threading.Lock()
    barrier = threading.Barrier(4)

    def read():
        barrier.wait()
        letters = box.take_unread("Ella Parker")
        with guard:
            collected.extend(letter["seq"] for letter in letters)

    threads = [threading.Thread(target=read) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(collected) == 50
    assert len(set(collected)) == 50                      # 没有一封被读两次


# ---------- 工具层 ----------

def _send(agent, world=None, **kwargs):
    args = {"thought": "worth asking", "to": "Ella Parker",
            "subject": "apples", "body": "Could you buy apples today?"}
    args.update(kwargs)
    return get_tool("send_mail").handler(agent, args, world)


def test_send_mail_tool_delivers_and_says_so(agent, monkeypatch, box):
    monkeypatch.setattr("world.mailbox.mailbox", box)
    result = _send(agent, World(time_minutes=10 * 60))

    assert result["ok"] is True
    assert "Ella Parker" in result["observation"]
    assert box.unread_counts() == {"Ella Parker": 1}


def test_send_mail_rejects_writing_to_yourself(agent, monkeypatch, box):
    monkeypatch.setattr("world.mailbox.mailbox", box)
    result = _send(agent, to="Ron Parker")

    assert result["ok"] is False
    assert result["reason"] == "self_addressed"


def test_send_mail_rejects_empty_body(agent, monkeypatch, box):
    monkeypatch.setattr("world.mailbox.mailbox", box)
    assert _send(agent, body="   ")["reason"] == "empty_body"


def test_check_inbox_returns_content_and_clears_the_flag(agent, monkeypatch, box):
    monkeypatch.setattr("world.mailbox.mailbox", box)
    box.send("Ella Parker", "Ron Parker", "dinner", "Shall we eat at seven?")

    result = get_tool("check_inbox").handler(agent, {"thought": "let me look"}, None)

    assert result["ok"] is True
    assert "Shall we eat at seven?" in result["observation"]
    assert box.unread_counts().get("Ron Parker", 0) == 0


def test_check_inbox_on_an_empty_box_is_a_success_not_a_failure(agent, monkeypatch, box):
    # 空手而归是有效结果：模型据此该停止翻邮箱，而不是当成错误重试。
    monkeypatch.setattr("world.mailbox.mailbox", box)
    result = get_tool("check_inbox").handler(agent, {"thought": "anything new?"}, None)

    assert result["ok"] is True
    assert result["letters"] == []


def test_mail_tools_cost_no_game_time(agent):
    # 改变世界却不占时间，所以不能收敛本轮——否则发完信就得再开一轮
    # 才能决定接下来干什么，白烧一次 LLM 调用。
    assert get_tool("send_mail").terminal is False
    assert get_tool("check_inbox").terminal is False
    assert get_tool("send_mail").max_per_turn == 1


# ---------- 感知：未读数免费，内容要花一步 ----------

def test_unread_count_rides_along_with_the_world_snapshot():
    world = World(time_minutes=10 * 60, agent_locations={},
                  unread_counts={"Ron Parker": 2, "Ella Parker": 0})
    assert world.unread_for("Ron Parker") == 2
    assert world.unread_for("Ella Parker") == 0
    assert world.unread_for("Nobody At All") == 0


def test_context_shows_the_count_but_never_the_content(agent, monkeypatch, box):
    monkeypatch.setattr("world.mailbox.mailbox", box)
    box.send("Ella Parker", "Ron Parker", "secret plan", "Meet me at the bridge at nine.")

    context = agent.build_decision_context(
        internal_state={"values": {}}, triggers=[], day_number=1,
        time_text="9:00 AM", current_location="Ron_home.Living_room",
        unread_letters=box.unread_counts()["Ron Parker"],
    )

    assert "1 unread letter" in context
    # 关键：正文一个字都不能出现在上下文里，否则就退回"被动喂"了。
    assert "bridge" not in context
    assert "secret plan" not in context


def test_no_mail_line_when_the_box_is_empty(agent):
    context = agent.build_decision_context(
        internal_state={"values": {}}, triggers=[], day_number=1,
        time_text="9:00 AM", current_location="Ron_home.Living_room",
        unread_letters=0,
    )
    assert "unread" not in context
