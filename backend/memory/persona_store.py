"""Per-agent evolving self-description ("persona").

The nightly reflection distils an agent's recent experience into a short
self-description paragraph. That paragraph is stored here, separate from the
raw memory bank, and injected back into the decision prompt so reflection
actually shapes future behaviour (reflection -> persona -> action).
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
        """Return the agent's current self-description, or None if unset."""
        path = self._path(agent_name)
        if not path.exists():
            return None
        try:
            with path.open(encoding="utf-8") as file:
                return (json.load(file).get("persona") or "").strip() or None
        except (OSError, json.JSONDecodeError):
            return None

    def set(self, agent_name, persona, life_day=None):
        """Persist a new self-description (atomic write). No-op for empty text."""
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


# Shared singleton used by reflection (writer) and agents (reader).
persona_store = PersonaStore()
