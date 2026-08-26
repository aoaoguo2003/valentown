from llm import LLMClient
from memory.memory_system import ReflectionRecord
from memory.persona_store import persona_store
from observability import trace_operation
from memory.retrieval import retriever

# 用于检索与身份认同相关的记忆，供更新 persona 时使用的查询语句。
IDENTITY_QUERY = (
    "personality traits, close relationships, personal values, recurring "
    "routines, and emotionally significant recent experiences"
)


class Reflection:
    def __init__(self, memory_system, agent_name):
        self.memory_system = memory_system
        self.agent_name = agent_name
        self.llm = LLMClient()

    def generate_reflection(self, life_day=None):
        """将最近的经历提炼为一段持续演化的自我描述文字。

        以与身份认同最相关的亲历记忆作为种子（采用三因子检索），并在
        agent 之前的自我描述基础上进行延伸，最终结果既会作为该 agent 的
        persona 存储（用于注入 prompt），也会作为一条 reflection 记忆存储
        （用于历史记录）。返回 (record, persona_text)；如果无法生成 persona，
        则返回一条提示信息和 None。"""
        if life_day is not None:
            self.memory_system.set_life_day(life_day)

        current_day = self.memory_system.current_life_day
        all_memories = self.memory_system.get_memories(agent_name=self.agent_name)

        # 只以亲历经历作为种子；持续演化的 persona 本身已经承载了过往的
        # 反思内容，排除 reflection 类记忆可以避免自我强化的回音室效应。
        experiences = [mem for mem in all_memories if mem.category != "reflection"]
        seed = retriever.retrieve(experiences, query=IDENTITY_QUERY, current_day=current_day, top_k=20)
        seed_context = "\n".join(f"- {mem.content}" for mem in seed) if seed else "No recent memory."

        previous_persona = persona_store.get(self.agent_name) or "No prior self-description yet."

        persona_context = (
            f"You are reflecting at the end of day {current_day} as {self.agent_name}.\n"
            f"Your previous self-description:\n{previous_persona}\n\n"
            f"Your most significant recent experiences:\n{seed_context}\n\n"
            "Write an updated self-description for this character in one paragraph of about "
            "80-120 words. Capture personality, key relationships, values, and how recent "
            "events have shifted them. Build on and evolve the previous self-description "
            "rather than discarding it. Write in the third person, plain English, no preamble."
        )

        with trace_operation("reflection", self.agent_name):
            persona = self.llm.get_response(self.agent_name, persona_context)

        if not persona:
            return (
                f"{self.agent_name} has not updated a self-description because there are "
                "insufficient recent memories.",
                None,
            )

        persona = persona.strip()
        persona_store.set(self.agent_name, persona, life_day=current_day)

        reflection_record = ReflectionRecord(
            f"{self.agent_name}: Self-reflection: {persona}",
            seed,
            level=1,
            agent_name=self.agent_name,
            life_day=current_day,
        )
        self.memory_system.add_reflection(
            reflection_record,
            agent_name=self.agent_name,
            life_day=current_day,
        )

        print(f"{self.agent_name} updated self-description:\n{persona}\n")
        return reflection_record, persona
