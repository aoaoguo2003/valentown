"""每个 agent 持续演化的自我描述（"persona"）。

每晚的反思（reflection）会把 agent 最近的经历提炼成一段简短的自我描述。这段
描述单独存储在这里，与原始的记忆库分开，并会被重新注入到决策 prompt 中，
使得反思真正能够影响未来的行为（reflection -> persona -> action）。
"""

import json
import threading
from datetime import datetime
from pathlib import Path

PERSONA_DIR = Path(__file__).with_name("agent_personas")


def persona_filename(agent_name):
    return agent_name.lower().replace(" ", "_") + ".json"


class PersonaStore:
    def __init__(self, persona_dir=PERSONA_DIR):
        self.persona_dir = Path(persona_dir)
        self._lock = threading.RLock()

    def _path(self, agent_name):
        return self.persona_dir / persona_filename(agent_name)

    def get(self, agent_name):
        """返回该 agent 当前的自我描述；如果尚未设置则返回 None。"""
        path = self._path(agent_name)
        if not path.exists():
            return None
        try:
            with path.open(encoding="utf-8") as file:
                return (json.load(file).get("persona") or "").strip() or None
        except (OSError, json.JSONDecodeError):
            return None

    def set(self, agent_name, persona, life_day=None):
        """持久化保存新的自我描述（原子写入）。如果文本为空则不执行任何操作。"""
        persona = (persona or "").strip()
        if not persona:
            return
        with self._lock:
            self.persona_dir.mkdir(parents=True, exist_ok=True)
            payload = {
                "agent_name": agent_name,
                "persona": persona,
                "life_day": life_day,
                "updated_at": datetime.now().isoformat(timespec="seconds"),
            }
            path = self._path(agent_name)
            temp_path = path.with_name(f".{path.name}.{threading.get_ident()}.tmp")
            with temp_path.open("w", encoding="utf-8") as file:
                json.dump(payload, file, ensure_ascii=False, indent=2)
            temp_path.replace(path)


# 由 reflection（写入方）和各个 agent（读取方）共用的单例对象。
persona_store = PersonaStore()
