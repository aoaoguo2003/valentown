"""上下文层：这一轮，让这个居民看见什么。

原本是 ``agents/agent.py`` 里一个 110 行、12 个参数的方法。搬出来不是为了
好看——是因为**它干的事跟"谁"无关**。七个居民用的是同一套组装规则，把规则
藏在角色定义里，规则就没有地方安放，只能以注释的形式散在函数体中间。

## 三条规则

这三条都不是设计出来的，是踩过坑之后定的。每条各自写在下面对应的段函数里。

**① 分界线是「这是关于谁的」，不是信息量。**
自己的东西（钱、背包、需求、位置、在办的事）随时知道，免费进；
别人的钱、店里的货、信的内容，都得花一个动作去取。

**② 当下免费，未来要查。**
抬头看得见的天气免费，未来几小时的预报要调 ``check_weather``。
天气正好横跨这条线，所以它是这条规则最好的例子。

**③ 本轮的经历分两段摆。**
"我刚知道的事实"和"这条路走不通"混在一起时长得一模一样，
那句"别重复被拒的"就淹没在列表里了——三天真跑里出现过 83 次同轮重复提问。

## 段

每一段是一个函数，签名一律 ``fn(agent, request) -> str``，返回带换行的一块或
空串。加东西就加一个函数，不是给那个方法加第十三个参数。

顺序有讲究，别随手调：靠前的是"你是谁、你在哪、你有什么"这类底子，
靠后的是"这一轮你已经试过什么"——最靠近要做的决定。
"""

from dataclasses import dataclass, field

from memory.persona_store import persona_store


@dataclass(frozen=True)
class ContextRequest:
    """一次决策要用到的全部输入。

    做成一个对象，是因为它已经长到十二样了——再往那个方法上加参数，
    调用方就得记住传哪十二个，而漏传一个不会报错，只会让模型少看见一样东西。
    """

    internal_state: dict
    triggers: list
    day_number: int
    time_text: str
    current_location: str
    last_action: str = None
    scratchpad: list = None
    visible_agents: list = None
    unread_letters: int = 0
    balance: int = None
    holdings: dict = None
    weather: str = None
    tasks: str = ""
    hidden_tools: list = field(default_factory=list)
    wanted_items: tuple = ()
    recent_events: tuple = ()
    omit: frozenset = frozenset()

    @property
    def values(self):
        return (self.internal_state or {}).get("values", {})

    @property
    def last_action_text(self):
        return self.last_action or "Just woke up; nothing done yet today."

    @property
    def trigger_lines(self):
        return "\n".join(
            f"- {trigger['need']}: {trigger['reason']} (intent: {trigger['intent']})"
            for trigger in (self.triggers or [])
        ) or "- No urgent needs right now."


# --- 段 ---------------------------------------------------------------------

def opening(agent, request):
    """时间、地点、你是谁。"""
    return (
        f"It is day {request.day_number}, {request.time_text} in Valentown. "
        f"Here is a basic description of you: {agent.character_description.strip()}\n"
    )


def who_you_have_become(agent, request):
    """每晚反思演化出来的自述，回灌进决策——反思 → persona → 行为的闭环。"""
    persona = persona_store.get(agent.name)
    return f"Your evolving self-reflection: {persona}\n" if persona else ""


def where_you_are(agent, request):
    """位置，以及**只有同一区域**的人。

    ⚠️ 世界知道所有人在哪，居民不知道。远处谁在哪不进上下文——想知道
    只能写信打听。这是通信之所以有存在意义的全部原因。
    """
    if request.visible_agents:
        return (f"You are currently at {request.current_location}.\n"
                f"People you can see from here: {', '.join(request.visible_agents)}.\n")
    return (f"You are currently at {request.current_location}.\n"
            f"You cannot see anyone else from here.\n")


def what_is_waiting(agent, request):
    """未读信的**数量**，不是内容。

    内容要花一步调 ``check_inbox``——全文自动塞进来，等于每次决策都为
    可能用不上的信付 token。

    ⚠️ 空邮箱也要明说。真跑两天：``check_inbox`` 被调了 49 次，其中
    **48 次空手而归**——因为"没信就不提示"让模型只能盲查。
    省下的那点字，换来的是四十八次完整的 LLM 调用。
    """
    if request.unread_letters:
        plural = "letter" if request.unread_letters == 1 else "letters"
        return f"You have {request.unread_letters} unread {plural} waiting in your mailbox.\n"
    return "Your mailbox is empty; nobody has written to you.\n"


def what_you_have(agent, request):
    """兜里的钱和身上的东西——**关于自己的，免费**。

    判据不是信息量大小，是"这是关于谁的"。曾经有个 ``check_balance`` 工具，
    三天被调用 161 次（Emma 一个人 43 次），而她的余额从头到尾没变过——
    每一次都是一整轮 LLM 调用，只为确认一件她本来就该知道的事。删了。
    """
    if request.balance is None:
        return ""
    carried = ", ".join(
        f"{item} x{count}"
        for item, count in sorted((request.holdings or {}).items()) if count > 0
    )
    return (f"You have {request.balance} in your purse and are carrying "
            f"{carried if carried else 'nothing'}.\n")


def what_it_is_like(agent, request):
    """**当前**天气免费——抬头就看得见。未来几小时要调 ``check_weather``。

    天气横跨"当下 vs 未来"这条线，是这条规则最干净的例子。
    """
    return f"The weather right now: {request.weather}.\n" if request.weather else ""


def what_you_owe(agent, request):
    """在办的差事和临近的约定。

    和未读信数量、余额、当前天气同级——免费。真跑的数据已经证明：
    不进上下文的东西，模型下一轮就忘了。
    """
    return request.tasks or ""


def what_you_could_do_elsewhere(agent, request):
    """此刻用不了、但确实存在的工具。

    它们的完整 schema 不进请求（一件 150-350 tokens），这里用一行代替
    （约 11 tokens）。**摘的是字数，不是能力**——看不见的能力模型不会为它
    做计划，只会在"当下能做什么"里打转。所以这句话必须点明它们还在。
    """
    if not request.hidden_tools:
        return ""
    listed = "; ".join(f"{name} ({why})" for name, why in request.hidden_tools)
    return (f"Also possible, but not from where you are right now: {listed}. "
            f"They still exist — move or get what you need first, then use them.\n")


def what_things_cost(agent, request):
    """在办的任务点名了什么物品，就给那几样的价钱。**不给整张价目表。**

    价格和库存是两回事，这条线值得划清楚：

        价格   静态、公开     谁都该知道咖啡多少钱   -> 免费，但只给相关的
        库存   会变、要到场   还剩几盒得自己去看     -> 花一步 check_stock

    起因是单步用例抓到的：Emma 站在药房里、兜里 3 块、任务是买退烧药，
    她点了 buy——三次都是。**她不是不会比大小，是不知道药要 8 块**：
    余额在上下文里，价格不在。缺的是那个 8，不是那个减法。

    ⚠️ 只给**事实**（多少钱），不给**结论**（你买不起）。这个代码库一直的
    分界就在这儿——余额、天气、看得见的人，给的都是事实。替它把差额算好，
    省下的是它本来就会的一步，换来的是再也测不出它会不会算。

    ⚠️ 只给整张表的一小块：34 tokens 的价目表九成时间是噪声，
    10 tokens 的一行正好落在用得着的那一刻。省的不是钱，是注意力。
    """
    if not request.wanted_items:
        return ""
    from world.economy import ITEM_SHOP, price_of

    lines = [f"{item} costs {price_of(item)} at the {ITEM_SHOP[item]}"
             for item in request.wanted_items if price_of(item) is not None]
    return f"What you need: {'; '.join(lines)}.\n" if lines else ""


def what_has_happened_since(agent, request):
    """上次行动之后，**世界里发生了什么他察觉得到的事**。

    这是上下文里唯一一段说"发生过"的——其余全是"现在是什么状态"。
    差别不是修辞：转账对收款人本来完全无声，Emma 写信借到的那 5 块钱到账时，
    她那边一个字都没有，只有余额从 3 变成了 8，得她自己发现。

    和"在撞墙那一刻指出那条路"是同一条经验：**事情发生的那一刻说一句，
    比让它自己盯着一个数字强。**

    ⚠️ 只说**状态覆盖不到**的事。未读信数量、在办的约定，上下文里本来就有，
    再播一遍只是费 token——所以那两类事件的 ``visible_to`` 是空的，只进日志。

    ⚠️ 看得见什么由 ``Event.visible_to`` 说了算，不由这里决定。别人买了什么
    你看不见——事件系统一旦变成全局广播，小镇的信息不对称就一次拆没了。
    """
    if not request.recent_events:
        return ""
    lines = "\n".join(f"- {event.describe_to(agent.name)}"
                      for event in request.recent_events)
    return f"Since you last acted:\n{lines}\n"


def what_just_happened(agent, request):
    """上一个动作，以及环境当时回了什么。"""
    line = f"What you just finished: {request.last_action_text}\n"
    if agent.last_observation:
        line += f"What you noticed last time: {agent.last_observation}\n"
    return line


def how_you_feel(agent, request):
    """需求值和被触发的需求。"""
    values = request.values
    return (
        f"Your internal needs (0-100): hunger {values.get('hunger', '?')}, "
        f"energy {values.get('energy', '?')}, social {values.get('social', '?')}.\n"
        f"Active need triggers:\n{request.trigger_lines}\n"
    )


def what_you_remember(agent, request):
    """三因子检索（新近度 x 重要性 x 相关性）出来的 top-12。

    检索用的 query 由此刻的处境拼成——同一批记忆，在药房和在公园召回的
    不该是同一组。
    """
    values = request.values
    query = (
        f"At {request.current_location}, {request.time_text}. "
        f"Needs - hunger {values.get('hunger', '?')}, energy {values.get('energy', '?')}, "
        f"social {values.get('social', '?')}. {request.trigger_lines} "
        f"Just finished: {request.last_action_text}"
    )
    return f"Your recent memories:\n{agent._recent_memory_context(query)}\n"


def what_you_tried_this_turn(agent, request):
    """本轮已经试过什么——**分两段**摆。

    ⚠️ 混在一起的话，"我刚知道的事实"和"这条路走不通"长得一模一样，
    那句"别重复被拒的"就淹没在列表里了。三天真跑里同轮重复提问出现了 83 次。

    两段的粒度也不同：**已经知道的只给结果**（哪个工具查到的无关紧要），
    **被拒绝的保留工具和参数**——要防的正是重复同一个调用。
    """
    if not request.scratchpad:
        return ""
    learned = [entry for entry in request.scratchpad if entry["ok"]]
    refused = [entry for entry in request.scratchpad if not entry["ok"]]
    parts = []
    if learned:
        facts = "\n".join(f"- {entry['observation']}" for entry in learned)
        parts.append(f"What you have found out this turn:\n{facts}")
    if refused:
        walls = "\n".join(
            f"- {entry['tool']}({entry['summary']}): {entry['observation']}"
            for entry in refused
        )
        parts.append(f"What the town refused this turn — do not try these again:\n{walls}")
    parts.append(
        "Use what you already know instead of asking again, and work around "
        "the refusals rather than repeating them."
    )
    return "\n".join(parts) + "\n"


def closing(agent, request):
    return ("Decide the single next thing you will do. Satisfy urgent needs first; "
            "otherwise act in character and vary your day. Use plain English only.")


# ⚠️ 顺序别随手调。靠前的是底子（你是谁、在哪、有什么），靠后的是这一轮
# 已经试过什么——最靠近要做的那个决定。
SECTIONS = (
    opening,
    who_you_have_become,
    where_you_are,
    what_is_waiting,
    what_you_have,
    what_it_is_like,
    what_you_owe,
    what_you_could_do_elsewhere,
    what_things_cost,
    what_has_happened_since,
    what_just_happened,
    how_you_feel,
    what_you_remember,
    what_you_tried_this_turn,
    closing,
)


SECTION_NAMES = frozenset(section.__name__ for section in SECTIONS)
"""消融想关哪一段，名字得在这里面——打错一个字就等于什么都没关。"""


def build(agent, request):
    """把所有段拼成一次决策的上下文。

    ``request.omit`` 里的段名会被跳过——**消融实验靠它**：关掉某一段再跑
    同一张记分卡，看任务达成率掉不掉。做成按段名关、而不是每做一个实验
    加一个布尔开关，是因为这样每一段都自动成了可测的一维。
    """
    return "".join(section(agent, request)
                   for section in SECTIONS if section.__name__ not in request.omit)
