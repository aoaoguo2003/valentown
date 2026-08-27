"""邮件：改变世界，却不占用游戏时间。

视野是受限的——居民只看得见同一区域的人。想知道别人在哪、想请人帮忙、
想问远处那家店有没有货，只能写信。这两个工具就是为了填上那个被刻意留出
的缺口，而它们**不占游戏时间**，所以发完信还能接着决定"这段时间干什么"。
"""

from tools.base import THOUGHT_FIELD, accept, reject
from world.locations import AGENT_NAMES


# --- send_mail：改变世界但不占用游戏时间 -----------------------------

SEND_MAIL_PARAMETERS = {
    "type": "object",
    "properties": {
        "thought": THOUGHT_FIELD,
        "to": {
            "type": "string",
            "enum": AGENT_NAMES,
            "description": "Which resident receives this letter.",
        },
        "subject": {
            "type": "string",
            "description": "A few words saying what the letter is about.",
        },
        "body": {
            "type": "string",
            "description": (
                "The letter itself, one or two sentences. Be concrete: say what "
                "you want, where, and when, so they can act on it."
            ),
        },
    },
    "required": ["thought", "to", "subject", "body"],
}


def handle_send_mail(agent, args, world=None):
    """给另一位居民写信。

    这是**改变世界却不占用游戏时间**的典型：对方收件箱确实多了一封信，
    但写一条短信不该占掉整个决策周期。所以它 ``ends_turn=False``——发完
    还能接着决定"接下来这段时间干什么"，比如原地等回音：

        send_mail(Ella, "能借我十块吗") -> stay("在药房等回音")

    若判它 ends_turn，发信和"决定接下来干嘛"就被拆成两个决策周期，白白
    多一次 LLM 调用。

    信送到就算成功，**不保证对方何时读到**：收件人要等下一次决策才可能
    看到未读提示，而两次决策之间隔着一个完整动作。发信人无从得知对方
    读没读——这正是异步通信该有的样子。
    """
    from world.mailbox import mailbox

    recipient = (args or {}).get("to")
    if recipient not in AGENT_NAMES:
        return reject("unknown_recipient", f"There is nobody called {recipient!r} in Valentown.")
    if recipient == agent.name:
        return reject("self_addressed", "Writing to yourself would not tell you anything new.")

    body = str((args or {}).get("body") or "").strip()
    if not body:
        return reject("empty_body", "You cannot send an empty letter.")

    subject = str((args or {}).get("subject") or "").strip() or "(no subject)"
    letter = mailbox.send(
        sender=agent.name,
        recipient=recipient,
        subject=subject,
        body=body,
        life_day=agent.memory.current_life_day,
        time_text=getattr(world, "time_text", None),
    )
    return accept(
        f"Your letter to {recipient} about {letter['subject']!r} has been delivered "
        f"to their mailbox. They will read it the next time they check.",
        letter=letter,
    )


# --- check_inbox：读信，同样不占用游戏时间 ---------------------------

CHECK_INBOX_PARAMETERS = {
    "type": "object",
    "properties": {"thought": THOUGHT_FIELD},
    "required": ["thought"],
}


def handle_check_inbox(agent, args, world=None):
    """读完所有未读信件。

    未读**数量**是免费的——它随世界快照进入决策上下文，居民不花任何代价
    就知道"有信该看了"。但信的**内容**要花一步来取：全文若也自动塞进
    上下文，那就是每一次决策都在为可能根本用不上的信件付 token，而绝大
    多数决策（吃饭、睡觉、散步）根本不需要看信。

    读取会就地标记已读，所以同一轮的下一步就会看到未读数归零，模型不会
    重复读同一批信。这个"取走并标记"是一个读-改-写序列，由 mailbox 内部
    的锁保证原子性。
    """
    from world.mailbox import mailbox

    letters = mailbox.take_unread(agent.name)
    if not letters:
        return accept("You check your mailbox. There is nothing new.", letters=[])

    body = "\n".join(
        f"- From {letter['from']} ({letter.get('time_text') or 'earlier'}), "
        f"{letter['subject']!r}: {letter['body']}"
        for letter in letters
    )
    plural = "letter" if len(letters) == 1 else "letters"
    # 读到请求的那一刻，正是提示"记下来"最有效的时机——比在系统提示里
    # 泛泛说一句"记得用 accept_task"有用得多。三天真跑里 accept_task
    # 一次都没被调用，而模型确实读过信。
    tail = (
        " If any of these asks you to do something that will take more than one "
        "move, use accept_task so it stays in front of you until it is done."
    )
    return accept(f"You read {len(letters)} {plural}:\n{body}{tail}", letters=letters)
