from llm import LLMClient
from observability import trace_operation
from retrieval import retriever
from memory.persona_store import persona_store

# 地点/居民常量与工具定义都在 tools.py：目的地白名单本质上就是 move_to
# 的参数取值范围。此处 re-export 是为了让既有调用方（含测试）不受影响。
from tools import (  # noqa: F401  （re-export）
    AGENT_NAMES,
    ALLOWED_DESTINATIONS,
    DEFAULT_ACTION_MINUTES,
    HOME_AREAS,
    HOME_ROOM_LOCATIONS,
    MAX_ACTION_MINUTES,
    MIN_ACTION_MINUTES,
    PUBLIC_LOCATIONS,
    build_allowed_destinations,
    function_schemas,
    get_tool,
)


class Agent:
    def __init__(self, name, age, role, personality, goals, memory, location, character_description):
        self.name = name                # 代理姓名
        self.age = age                  # 代理年龄
        self.role = role                # 在村庄中的角色（如父亲、教师等）
        self.personality = personality  # 个性描述（如热心、内向等）
        self.goals = goals              # 代理的目标
        self.memory = memory            # 记忆系统对象（支持反思、持久化）
        self.location = location        # 初始位置
        self.current_location = location  # 当前所在位置（随决策更新）
        self.last_observation = None    # 上一次动作执行后环境返回的反馈
        self.character_description = character_description  # 自定义角色描述
        self.llm = LLMClient()

    @property
    def home_area(self):
        first_name = self.name.split(" ")[0]
        return f"{first_name}_home"

    def update_memory(self, new_memory, category="action", importance=None, life_day=None, fallback_importance=4):
        """将一条新记忆添加到该代理自身的滚动记忆库中。

        当未提供 ``importance`` 时，由 LLM 对该记忆的深刻程度打分
        （1-10 分），使日常琐事得分较低、而有意义的时刻得分较高；
        若 LLM 不可用，则回退使用 ``fallback_importance``。"""
        full_memory = f"{self.name}: {new_memory}"
        if importance is None:
            importance = self.llm.rate_importance(self.name, full_memory, fallback=fallback_importance)
        self.memory.add_memory(full_memory, category, importance, agent_name=self.name, life_day=life_day)

    def record_completed_action(self, action_text, location, life_day=None):
        """持久化一个已完成的动作，以便未来的决策可以基于它来展开。"""
        if not action_text:
            return
        with trace_operation("action_memory", self.name):
            self.update_memory(
                f"Did '{action_text}' at {location}.",
                category="action",
                life_day=life_day,
                fallback_importance=3
            )

    def _recent_memory_context(self, query, limit=12):
        """通过三因子评分（新近度 x 重要性 x 相关性）检索与 ``query``
        最相关的记忆，并格式化为项目符号列表。"""
        records = self.memory.get_memories(agent_name=self.name)
        if not records:
            return "No recent memories."
        top = retriever.retrieve(
            records,
            query=query,
            current_day=self.memory.current_life_day,
            top_k=limit,
        )
        return "\n".join(f"- {record.content}" for record in top) if top else "No recent memories."

    def build_decision_context(self, internal_state, triggers, day_number, time_text,
                               current_location, last_action=None, scratchpad=None,
                               visible_agents=None, unread_letters=0, balance=None,
                               weather=None, tasks="", holdings=None):
        """组装一次决策所需的全部上下文。

        循环的每一步都会重新调用它，因为 ``scratchpad``（本轮已经试过
        什么、环境回了什么）每一步都在变。把它从决策方法里拆出来，正是
        为了让"想一次"和"想很多次"共用同一套上下文规则。

        ``visible_agents`` 只包含此刻和自己处在同一区域的人——这是居民
        能合法获知的全部他人位置信息。远处谁在哪不进上下文，想知道只能
        靠打听。
        """
        values = (internal_state or {}).get("values", {})
        trigger_lines = "\n".join(
            f"- {trigger['need']}: {trigger['reason']} (intent: {trigger['intent']})"
            for trigger in (triggers or [])
        ) or "- No urgent needs right now."
        last_action_text = last_action or "Just woke up; nothing done yet today."

        retrieval_query = (
            f"At {current_location}, {time_text}. "
            f"Needs - hunger {values.get('hunger', '?')}, energy {values.get('energy', '?')}, "
            f"social {values.get('social', '?')}. {trigger_lines} "
            f"Just finished: {last_action_text}"
        )

        persona = persona_store.get(self.name)
        persona_line = f"Your evolving self-reflection: {persona}\n" if persona else ""

        if visible_agents:
            here_line = f"People you can see from here: {', '.join(visible_agents)}.\n"
        else:
            here_line = "You cannot see anyone else from here.\n"

        # 未读**数量**是免费的，和"你饿了"这类需求提示走同一条路；信的
        # **内容**仍然要花一步调 check_inbox 去取。全文若也自动塞进来，
        # 就等于每次决策都为可能用不上的信件付 token。
        if unread_letters:
            plural = "letter" if unread_letters == 1 else "letters"
            mail_line = (
                f"You have {unread_letters} unread {plural} waiting in your mailbox.\n"
            )
        else:
            # 空邮箱也要明说。真跑两天的数据：check_inbox 被调了 49 次，
            # 其中 48 次空手而归——因为"没信就不提示"让模型只能盲查。
            mail_line = "Your mailbox is empty; nobody has written to you.\n"

        # 钱和随身物品都是**免费**的自我感知：自己兜里有什么，不必花一步去数。
        # 判据不是信息量大小，而是"这是关于谁的"——自己的东西随时知道，
        # 别人的钱、店里的货、信的内容都得动作才能得知。
        if balance is not None:
            carried = ", ".join(
                f"{item} x{count}" for item, count in sorted((holdings or {}).items()) if count > 0
            )
            purse_line = (
                f"You have {balance} in your purse and are carrying "
                f"{carried if carried else 'nothing'}.\n"
            )
        else:
            purse_line = ""

        # 当前天气免费——抬头就能看见。未来几小时要调 check_weather 才知道。
        weather_line = f"The weather right now: {weather}.\n" if weather else ""

        # 在办的任务免费进上下文，和未读信数量、余额、当前天气同级。
        # 真跑的数据已经证明：不进上下文的东西，模型下一轮就忘了。
        task_line = tasks or ""

        observation_line = (
            f"What you noticed last time: {self.last_observation}\n"
            if self.last_observation else ""
        )

        # 本轮的经历分两类摆出来。混在一起的话，"我刚知道的事实"和"这条路
        # 走不通"长得一模一样，那句"别重复被拒的"也就淹没在列表里了——
        # 三天真跑里出现了 83 次同一轮内重复提问。
        scratchpad_block = ""
        if scratchpad:
            learned = [entry for entry in scratchpad if entry["ok"]]
            refused = [entry for entry in scratchpad if not entry["ok"]]
            parts = []
            if learned:
                facts = "\n".join(f"- {entry['observation']}" for entry in learned)
                parts.append(f"What you have found out this turn:\n{facts}")
            if refused:
                walls = "\n".join(
                    f"- {entry['tool']}({entry['summary']}): {entry['observation']}"
                    for entry in refused
                )
                parts.append(
                    f"What the town refused this turn — do not try these again:\n{walls}"
                )
            parts.append(
                "Use what you already know instead of asking again, and work around "
                "the refusals rather than repeating them."
            )
            scratchpad_block = "\n".join(parts) + "\n"

        return (
            f"It is day {day_number}, {time_text} in Valentown. "
            f"Here is a basic description of you: {self.character_description.strip()}\n"
            f"{persona_line}"
            f"You are currently at {current_location}.\n"
            f"{here_line}"
            f"{mail_line}"
            f"{purse_line}"
            f"{weather_line}"
            f"{task_line}"
            f"What you just finished: {last_action_text}\n"
            f"{observation_line}"
            f"Your internal needs (0-100): hunger {values.get('hunger', '?')}, "
            f"energy {values.get('energy', '?')}, social {values.get('social', '?')}.\n"
            f"Active need triggers:\n{trigger_lines}\n"
            f"Your recent memories:\n{self._recent_memory_context(retrieval_query)}\n"
            f"{scratchpad_block}"
            "Decide the single next thing you will do. Satisfy urgent needs first; "
            "otherwise act in character and vary your day. Use plain English only."
        )

    def decide_next_action(self, internal_state, triggers, day_number, time_text,
                           current_location, last_action=None, world=None):
        """单步决策：强制调用 move_to，一次定一个动作。

        这是改造前的决策方式，现在只保留给两处使用：不需要多步推理的
        调用方，以及测试。真正的多步决策在 ``runtime.py`` 的循环里，
        那里模型会自己在工具之间做选择。
        """
        self.memory.set_life_day(day_number or 1)

        context = self.build_decision_context(
            internal_state, triggers, day_number, time_text, current_location, last_action
        )
        move_to = get_tool("move_to")

        with trace_operation("decision", self.name):
            arguments = self.llm.call_tool(
                self.name,
                context,
                tool_name=move_to.name,
                tool_description=move_to.description,
                parameters=move_to.to_function_schema(self.name)["function"]["parameters"]
            )

        result = move_to.handler(self, arguments, world)
        if result["ok"]:
            decision = dict(result["decision"])
            decision["source"] = "llm"
            return decision

        fallback = self.fallback_next_action(triggers)
        fallback["source"] = "fallback"
        return fallback

    def fallback_next_action(self, triggers):
        """当 LLM 不可用时使用的确定性、由需求驱动的规则，
        以确保模拟过程不会停滞。"""
        top_trigger = (triggers or [None])[0]
        need = top_trigger.get("need") if isinstance(top_trigger, dict) else None

        if need == "hunger":
            return {
                "action": "eat something at home",
                "destination": f"{self.home_area}.Kitchen",
                "duration_minutes": 45,
                "talk_to": "nobody"
            }
        if need == "energy":
            return {
                "action": "rest on the sofa",
                "destination": f"{self.home_area}.Sofa",
                "duration_minutes": 60,
                "talk_to": "nobody"
            }
        if need == "social":
            return {
                "action": "look for a friend in the park",
                "destination": "Park.Bench",
                "duration_minutes": 60,
                "talk_to": "nobody"
            }
        return {
            "action": "take a relaxing walk in the park",
            "destination": "Park.Bench",
            "duration_minutes": DEFAULT_ACTION_MINUTES,
            "talk_to": "nobody"
        }

    def talk_with(self, target_agent, day_number, location):
        """与明确选定的对话对象生成一段简短的两句问答；
        对话双方都会记住这次交流。"""
        self.memory.set_life_day(day_number or 1)

        with trace_operation("dialogue", self.name):
            question_context = (
                f"You are {self.name}, talking to {target_agent.name} at {location}.\n"
                f"Your recent memories:\n{self._recent_memory_context(f'Talking to {target_agent.name} at {location}', limit=8)}\n"
                "Use plain English only. "
                f"Just act as {self.name} ({self.age} years old) and say one line of about 10 words. "
                "Do not describe actions."
            )
            question = self.llm.get_response(self.name, question_context)
            if not question:
                return None

            answer_context = (
                f"You are {target_agent.name}, answering {self.name} at {location}.\n"
                f"They just said: {question}\n"
                "Use plain English only. "
                f"Just act as {target_agent.name} ({target_agent.age} years old) and reply in about 10 words. "
                "Do not describe actions."
            )
            answer = target_agent.llm.get_response(target_agent.name, answer_context)
            if not answer:
                return None

            # 保存双向记忆：对整段对话评一次重要性，双方共用，省一次 LLM 调用
            convo_importance = self.llm.rate_importance(
                self.name,
                f"{self.name} and {target_agent.name} talked at {location}: "
                f"\"{question}\" / \"{answer}\"",
                fallback=6
            )
            self.update_memory(
                f"Talked to {target_agent.name} at {location}: \"{question}\"",
                category="communication",
                importance=convo_importance,
                life_day=day_number
            )
            target_agent.update_memory(
                f"Replied to {self.name} at {location}: \"{answer}\"",
                category="communication",
                importance=convo_importance,
                life_day=day_number
            )

        return {
            "initiator": self.name,
            "responder": target_agent.name,
            "location": location,
            "question": question,
            "answer": answer
        }


class RonParker(Agent):
    def __init__(self, memory, location):
        character_description = """
        Ron Parker is a warm-hearted man in his 60s who co-owns the Valentown Supermarket with his wife, Ella.
        He's known for his generosity and helpful nature. Ron enjoys chatting with customers, offering advice.
        He's especially close to his wife, Ella.
        """
        super().__init__("Ron Parker", 60, "Supermarket and Pharmacy Owner", "warm-hearted",
                         ["chess enthusiasts", "run business", "enjoy relax"], memory, location, character_description)

class EllaParker(Agent):
    def __init__(self, memory, location):
        character_description = """
        Ella Parker is a compassionate and meticulous woman in her 58s, who co-owns the Valentown Pharmacy with her husband, Ron.
        She takes great pride in managing the pharmacy, always eager to help customers with their health needs and provide them with the best care.
        Ella is highly organized and ensures the business runs smoothly, complementing Ron's more sociable approach with her methodical and thoughtful nature.
        """
        super().__init__("Ella Parker", 58, "Supermarket and Pharmacy Owner", "compassionate",
                         ["manage pharmacy", "help customers", "humor"], memory, location, character_description)

class EmmaHarris(Agent):
    def __init__(self, memory, location):
        character_description = """
        Emma Harris is a dedicated and caring mother in her early 30s, living in Valentown with her husband, Gavin, and their 7-year-old son, Adam.
        As a full-time mother, Emma's life revolves around nurturing her family and maintaining a balanced household. She is kind-hearted, always willing to lend a helping hand to her neighbors and fellow parents, and is always happy to play with friends.
        """
        super().__init__("Emma Harris", 30, "Mother", "caring",
                         ["play with friends", "support community", "educate child"], memory, location, character_description)

class GavinHarris(Agent):
    def __init__(self, memory, location):
        character_description = """
        Gavin Harris is a 32-year-old father and husband, known for his easygoing yet responsible nature. He is deeply committed to his family and plays an active role in raising his son, Adam, alongside his wife, Emma.
        Gavin enjoys spending time outdoors, often taking Adam to the park or engaging in sports with him. Gavin values a hands-on approach to fatherhood, and he often works together with Emma to create a nurturing home environment.
        """
        super().__init__("Gavin Harris", 32, "Father", "responsible",
                         ["spend time with family", "work on family life", "love sport"], memory, location, character_description)

class AdamHarris(Agent):
    def __init__(self, memory, location):
        character_description = """
        Adam Harris is a lively and curious 7-year-old boy, full of energy and wonder about the world around him. He is bright and inquisitive, asking endless questions and eager to learn about everything he encounters. Adam enjoys exploring Valentown, often visiting the park with his parents or running errands to the supermarket with his dad.
        """
        super().__init__("Adam Harris", 7, "Child", "curious",
                         ["explore", "learn from adults", "play with friends"], memory, location, character_description)

class MiaThompson(Agent):
    def __init__(self, memory, location):
        character_description = """
        Mia Thompson is a thoughtful and compassionate young woman in her late 20s, working as a family teacher in Valentown. She is passionate about educating children and helping families navigate the challenges of raising young ones.
        Mia has a close, supportive relationship with the Harris family, especially with Emma, with whom she frequently discusses the best ways to nurture Adam’s education and development, and is always happy to play with friends.
        """
        super().__init__("Mia Thompson", 28, "Family Teacher", "thoughtful",
                         ["teach children", "play with friends", "optimistic"], memory, location, character_description)

class ArthurMorgan(Agent):
    def __init__(self, memory, location):
        character_description = """
        Arthur Morgan is a thoughtful and ambitious young architect in his late 20s, with a keen eye for design and a passion for creating spaces that foster community. He is known for his quiet, introspective nature, preferring to observe and reflect before engaging in conversation.
        Arthur often chats with Ron and Ella Parker about the layout of the supermarket and pharmacy, offering suggestions for improvements to optimize space and efficiency.
        """
        super().__init__("Arthur Morgan", 29, "Architect", "reserved",
                         ["chess enthusiasts", "reflect on architecture", "work hard"], memory, location, character_description)
