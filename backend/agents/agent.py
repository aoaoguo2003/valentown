from llm import LLMClient
from observability import trace_operation
from memory.retrieval import retriever
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
                               weather=None, tasks="", holdings=None,
                               hidden_tools=None, wanted_items=(),
                               recent_events=(), omit_context=()):
        """组装一次决策所需的全部上下文。

        真正的规则在 ``runtime/context_builder.py``——那一层跟"谁"无关，
        七个居民用的是同一套。这里留一层薄壳，是因为组装需要居民自己的
        东西（角色描述、上一条 observation、他的记忆库），而且既有调用方
        不必知道内部怎么分的段。

        循环的每一步都会重新调用它，因为 ``scratchpad``（本轮试过什么、
        环境回了什么）每一步都在变。
        """
        from runtime.context_builder import ContextRequest, build

        return build(self, ContextRequest(
            internal_state=internal_state,
            triggers=triggers,
            day_number=day_number,
            time_text=time_text,
            current_location=current_location,
            last_action=last_action,
            scratchpad=scratchpad,
            visible_agents=visible_agents,
            unread_letters=unread_letters,
            balance=balance,
            holdings=holdings,
            weather=weather,
            tasks=tasks,
            hidden_tools=hidden_tools or [],
            wanted_items=tuple(wanted_items),
            recent_events=tuple(recent_events),
            omit=frozenset(omit_context),
        ))

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
