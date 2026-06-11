from llm import LLMClient
from observability import trace_operation
from retrieval import retriever
from memory.persona_store import persona_store

HOME_AREAS = [
    "Ron_home",
    "Ella_home",
    "Arthur_home",
    "Mia_home",
    "Emma_home",
    "Gavin_home",
    "Adam_home",
]

HOME_ROOM_LOCATIONS = [
    "Living_room",
    "Kitchen",
    "Dining_table",
    "Dinning_room",
    "Study_corner",
    "Desk",
    "Bookshelf",
    "Reading_chair",
    "Sofa",
    "Chair",
    "Porch",
    "Window",
]

PUBLIC_LOCATIONS = [
    "Park.Chair",
    "Park.River",
    "Park.Tree",
    "Park.Bench",
    "Park.Flower_bed",
    "Park.Playground",
    "Park.Bridge",
    "Café_bar.Boss",
    "Café_bar.Customer_cafe",
    "Café_bar.Customer_bar",
    "Café_bar.Window_seat",
    "Café_bar.Corner_table",
    "Café_bar.Counter",
    "Café_bar.Patio",
    "Supermarket.Boss",
    "Supermarket.Customer_drink",
    "Supermarket.Customer_eat",
    "Supermarket.Checkout",
    "Supermarket.Fruit_shelf",
    "Supermarket.Storage",
    "Supermarket.Entrance_aisle",
    "Pharmacy.Boss",
    "Pharmacy.Customer_left",
    "Pharmacy.Customer_right",
    "Pharmacy.Prescription_counter",
    "Pharmacy.Medicine_shelf",
    "Pharmacy.Waiting_chair",
    "Pharmacy.Consult_room",
]

AGENT_NAMES = [
    "Ron Parker",
    "Ella Parker",
    "Emma Harris",
    "Gavin Harris",
    "Adam Harris",
    "Mia Thompson",
    "Arthur Morgan",
]

# Decision bounds for one action, in game minutes.
MIN_ACTION_MINUTES = 15
MAX_ACTION_MINUTES = 180
DEFAULT_ACTION_MINUTES = 60


def build_allowed_destinations():
    """Every navigable anchor an agent may pick as a destination. Bedrooms and
    toilets are deliberately absent from HOME_ROOM_LOCATIONS, so privacy rules
    are enforced by construction instead of by prompt instructions."""
    home_locations = [
        f"{home_area}.{room_name}"
        for home_area in HOME_AREAS
        for room_name in HOME_ROOM_LOCATIONS
    ]
    return home_locations + PUBLIC_LOCATIONS


ALLOWED_DESTINATIONS = build_allowed_destinations()


class Agent:
    def __init__(self, name, age, role, personality, goals, memory, location, character_description):
        self.name = name                # 代理姓名
        self.age = age                  # 代理年龄
        self.role = role                # 在村庄中的角色（如父亲、教师等）
        self.personality = personality  # 个性描述（如热心、内向等）
        self.goals = goals              # goals of agents
        self.memory = memory            # 记忆系统对象（支持反思、持久化）
        self.location = location        # 初始位置
        self.current_location = location  # 当前所在位置（随决策更新）
        self.character_description = character_description  # 自定义角色描述
        self.llm = LLMClient()

    @property
    def home_area(self):
        first_name = self.name.split(" ")[0]
        return f"{first_name}_home"

    def update_memory(self, new_memory, category="action", importance=None, life_day=None, fallback_importance=4):
        """Add a new memory to this agent's own rolling memory bank.

        When ``importance`` is not given, the LLM rates the memory's poignancy
        (1-10) so routine actions land low and meaningful moments land high,
        falling back to ``fallback_importance`` if the LLM is unavailable."""
        full_memory = f"{self.name}: {new_memory}"
        if importance is None:
            importance = self.llm.rate_importance(self.name, full_memory, fallback=fallback_importance)
        self.memory.add_memory(full_memory, category, importance, agent_name=self.name, life_day=life_day)

    def record_completed_action(self, action_text, location, life_day=None):
        """Persist a finished action so future decisions can build on it."""
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
        """Retrieve the memories most relevant to ``query`` via three-factor
        scoring (recency x importance x relevance), formatted as a bullet list."""
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

    def decide_next_action(self, internal_state, triggers, day_number, time_text, current_location, last_action=None):
        """Pick the next action via a forced function call; fall back to the
        deterministic need-driven rules whenever the LLM is unavailable or
        returns an invalid destination."""
        self.memory.set_life_day(day_number or 1)

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

        context = (
            f"It is day {day_number}, {time_text} in Valentown. "
            f"Here is a basic description of you: {self.character_description.strip()}\n"
            f"{persona_line}"
            f"You are currently at {current_location}.\n"
            f"What you just finished: {last_action_text}\n"
            f"Your internal needs (0-100): hunger {values.get('hunger', '?')}, "
            f"energy {values.get('energy', '?')}, social {values.get('social', '?')}.\n"
            f"Active need triggers:\n{trigger_lines}\n"
            f"Your recent memories:\n{self._recent_memory_context(retrieval_query)}\n"
            "Decide the single next thing you will do. Satisfy urgent needs first; "
            "otherwise act in character and vary your day. Use plain English only."
        )

        other_names = [name for name in AGENT_NAMES if name != self.name]
        parameters = {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "What to do next, about 10 plain-English words."
                },
                "destination": {
                    "type": "string",
                    "enum": ALLOWED_DESTINATIONS,
                    "description": "Where to do it. Must be one of the listed anchors."
                },
                "duration_minutes": {
                    "type": "integer",
                    "minimum": MIN_ACTION_MINUTES,
                    "maximum": MAX_ACTION_MINUTES,
                    "description": "How long the action takes, in game minutes."
                },
                "talk_to": {
                    "type": "string",
                    "enum": other_names + ["nobody"],
                    "description": "Who to talk to while there, or 'nobody'."
                }
            },
            "required": ["action", "destination", "duration_minutes", "talk_to"]
        }

        with trace_operation("decision", self.name):
            decision = self.llm.call_tool(
                self.name,
                context,
                tool_name="choose_next_action",
                tool_description="Choose the single next action for this resident.",
                parameters=parameters
            )

        validated = self._validate_decision(decision)
        if validated:
            validated["source"] = "llm"
            return validated

        fallback = self.fallback_next_action(triggers)
        fallback["source"] = "fallback"
        return fallback

    def _validate_decision(self, decision):
        """Defensive validation of the tool-call output; returns a normalized
        decision dict or None when the structure cannot be trusted."""
        if not isinstance(decision, dict):
            return None

        destination = decision.get("destination")
        if destination not in ALLOWED_DESTINATIONS:
            return None

        action = str(decision.get("action") or "").strip()
        if not action:
            return None

        try:
            duration = int(decision.get("duration_minutes"))
        except (TypeError, ValueError):
            duration = DEFAULT_ACTION_MINUTES
        duration = max(MIN_ACTION_MINUTES, min(MAX_ACTION_MINUTES, duration))

        talk_to = decision.get("talk_to")
        if talk_to not in AGENT_NAMES or talk_to == self.name:
            talk_to = "nobody"

        return {
            "action": action,
            "destination": destination,
            "duration_minutes": duration,
            "talk_to": talk_to
        }

    def fallback_next_action(self, triggers):
        """Deterministic need-driven rules used when the LLM is unavailable,
        so the simulation never stalls."""
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
        """Generate a short two-line exchange with an explicitly chosen
        partner; both sides remember the conversation."""
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
