from llm import LLMClient
from memory.memory_system import ReflectionRecord


class Reflection:
    def __init__(self, memory_system, agent_name):
        self.memory_system = memory_system
        self.agent_name = agent_name
        self.llm = LLMClient()

    def generate_reflection(self, life_day=None):
        if life_day is not None:
            self.memory_system.set_life_day(life_day)

        all_memories = self.memory_system.get_memories(agent_name=self.agent_name)

        # Seed reflection from lived experience only; excluding prior reflections
        # prevents an echo chamber where the agent reflects on its own reflections.
        experiences = [mem for mem in all_memories if mem.category != "reflection"]

        # Rank by a combined importance + recency score (closer lived days score
        # higher) so the seed is not dominated purely by static importance values.
        current_day = self.memory_system.current_life_day

        def relevance_score(mem):
            recency = max(0, current_day - (mem.life_day or current_day))
            return mem.importance - recency

        recent_memories = sorted(experiences, key=relevance_score, reverse=True)[:20]
        recent_memory_context = "\n".join(f"- {mem.content}" for mem in recent_memories) if recent_memories else "No recent memory."

        question_context = (
            f"Based only on the recent rolling memories of {self.agent_name}:\n{recent_memory_context}\n"
            "Generate 3 significant high-level questions about this agent's motives, relationships, or routines. "
            "Use plain English only. Return only the 3 questions."
        )
        questions = self.llm.get_response(self.agent_name, question_context)

        reflection_context = (
            f"Answer these high-level questions using only {self.agent_name}'s recent rolling memories:\n{questions}\n"
            "Return 3 concise insights. Use plain English only."
        )
        answer = self.llm.get_response(self.agent_name, reflection_context)

        print(f"{self.agent_name} is thinking:\n")
        print(answer, "\n")

        if answer:
            reflection_text = f"{self.agent_name}: Reflection: {answer}"
            reflection_record = ReflectionRecord(
                reflection_text,
                recent_memories,
                level=1,
                agent_name=self.agent_name,
                life_day=life_day or self.memory_system.current_life_day
            )
            self.memory_system.add_reflection(
                reflection_record,
                agent_name=self.agent_name,
                life_day=life_day or self.memory_system.current_life_day
            )
            return reflection_record, answer

        return f"{self.agent_name} has not generated a reflection because there are insufficient recent memories.", None
