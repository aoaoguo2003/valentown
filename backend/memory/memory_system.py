import json
import re
import threading
from datetime import datetime
from pathlib import Path


MEMORY_BANK_DIR = Path(__file__).with_name("agent_memory_banks")
RETENTION_DAYS = 15


def agent_memory_filename(agent_name):
    return agent_name.lower().replace(" ", "_") + ".json"


def infer_agent_name_from_content(content):
    match = re.match(r"^\s*([^:]+):", str(content or ""))
    return match.group(1).strip() if match else None


class MemoryRecord:
    def __init__(self, content, category, importance, agent_name=None, life_day=None, timestamp=None):
        self.content = content
        self.category = category
        self.importance = importance
        self.agent_name = agent_name
        self.life_day = life_day
        self.timestamp = timestamp if timestamp is not None else datetime.now()

    def to_dict(self):
        return {
            "content": self.content,
            "category": self.category,
            "importance": self.importance,
            "agent_name": self.agent_name,
            "life_day": self.life_day,
            "timestamp": self.timestamp.isoformat()
        }

    @staticmethod
    def from_dict(data):
        return MemoryRecord(
            content=data["content"],
            category=data["category"],
            importance=data["importance"],
            agent_name=data.get("agent_name"),
            life_day=data.get("life_day"),
            timestamp=datetime.fromisoformat(data["timestamp"])
        )

    def __repr__(self):
        return (
            f"MemoryRecord(agent_name={self.agent_name}, category={self.category}, "
            f"importance={self.importance}, life_day={self.life_day}, content={self.content})"
        )


class ReflectionRecord(MemoryRecord):
    def __init__(self, content, base_memories, level, agent_name=None, life_day=None, timestamp=None):
        super().__init__(
            content,
            category="reflection",
            importance=10,
            agent_name=agent_name,
            life_day=life_day,
            timestamp=timestamp
        )
        self.base_memories = base_memories
        self.level = level

    def to_dict(self):
        data = super().to_dict()
        data["level"] = self.level
        data["base_memories"] = [mem.to_dict() for mem in self.base_memories]
        return data

    @staticmethod
    def from_dict(data):
        base_memories = [MemoryRecord.from_dict(item) for item in data.get("base_memories", [])]
        return ReflectionRecord(
            content=data["content"],
            base_memories=base_memories,
            level=data.get("level", 1),
            agent_name=data.get("agent_name"),
            life_day=data.get("life_day"),
            timestamp=datetime.fromisoformat(data["timestamp"])
        )


class MemorySystem:
    def __init__(self, retention_days=RETENTION_DAYS, memory_dir=MEMORY_BANK_DIR):
        self.retention_days = retention_days
        self.memory_dir = Path(memory_dir)
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.current_life_day = 1
        self.memories = []
        self._lock = threading.RLock()

    def initialize_agents(self, agent_names):
        with self._lock:
            for agent_name in agent_names:
                self._save_bank(agent_name, self._load_bank(agent_name))
            self._refresh_cache(agent_names)

    def set_life_day(self, life_day, agent_names=None):
        with self._lock:
            self.current_life_day = max(1, int(life_day or 1))
            if agent_names:
                for agent_name in agent_names:
                    bank = self._load_bank(agent_name)
                    self._save_bank(agent_name, bank)
                self._refresh_cache(agent_names)

    def add_memory(self, content, category, importance, agent_name=None, life_day=None):
        resolved_agent_name = agent_name or infer_agent_name_from_content(content)
        if not resolved_agent_name:
            raise ValueError("agent_name is required for agent-specific memory")

        with self._lock:
            resolved_life_day = int(life_day or self.current_life_day)
            memory = MemoryRecord(content, category, importance, resolved_agent_name, resolved_life_day)
            bank = self._load_bank(resolved_agent_name)
            bank["memories"].append(memory.to_dict())
            self._save_bank(resolved_agent_name, bank)
            self._refresh_cache()
            return memory

    def add_reflection(self, reflection_record, agent_name=None, life_day=None):
        resolved_agent_name = agent_name or reflection_record.agent_name or infer_agent_name_from_content(reflection_record.content)
        with self._lock:
            reflection_record.agent_name = resolved_agent_name
            reflection_record.life_day = int(life_day or reflection_record.life_day or self.current_life_day)
            bank = self._load_bank(resolved_agent_name)
            bank["memories"].append(reflection_record.to_dict())
            self._save_bank(resolved_agent_name, bank)
            self._refresh_cache()
            return reflection_record

    def get_recent_plans(self, agent_name=None):
        return self.get_memories(agent_name=agent_name, category="daily_plan")

    def get_recent_reflections(self, agent_name=None):
        return self.get_memories(agent_name=agent_name, category="reflection")

    def get_memories(self, agent_name=None, category=None):
        with self._lock:
            records = self._load_records(agent_name)
            if category:
                records = [record for record in records if record.category == category]
            return sorted(records, key=lambda record: (record.life_day or 0, record.timestamp), reverse=True)

    def get_agent_memory_bank(self, agent_name):
        with self._lock:
            bank = self._load_bank(agent_name)
            bank["memories"] = [record.to_dict() for record in self._records_from_bank(bank)]
            return bank

    def save_to_file(self, filename=None):
        with self._lock:
            self._refresh_cache()
            if filename:
                manifest = {
                    "memory_model": "agent_specific_rolling_memory",
                    "retention_days": self.retention_days,
                    "current_life_day": self.current_life_day,
                    "memory_bank_dir": str(self.memory_dir),
                    "agents": sorted({record.agent_name for record in self.memories if record.agent_name})
                }
                with open(filename, "w", encoding="utf-8") as file:
                    json.dump(manifest, file, ensure_ascii=False, indent=4)

    def _bank_path(self, agent_name):
        return self.memory_dir / agent_memory_filename(agent_name)

    def _empty_bank(self, agent_name):
        return {
            "agent_name": agent_name,
            "retention_days": self.retention_days,
            "current_life_day": self.current_life_day,
            "memories": []
        }

    def _load_bank(self, agent_name):
        path = self._bank_path(agent_name)
        if not path.exists():
            return self._empty_bank(agent_name)

        try:
            with path.open("r", encoding="utf-8") as file:
                bank = json.load(file)
        except json.JSONDecodeError:
            bank = self._empty_bank(agent_name)

        bank.setdefault("agent_name", agent_name)
        bank.setdefault("retention_days", self.retention_days)
        bank.setdefault("current_life_day", self.current_life_day)
        bank.setdefault("memories", [])
        return bank

    def _save_bank(self, agent_name, bank):
        bank["agent_name"] = agent_name
        bank["retention_days"] = self.retention_days
        bank["current_life_day"] = self.current_life_day
        records = self._records_from_bank(bank)
        records = self._prune_records(records)
        bank["memories"] = [record.to_dict() for record in records]

        path = self._bank_path(agent_name)
        temp_path = path.with_name(f".{path.name}.{threading.get_ident()}.tmp")
        with temp_path.open("w", encoding="utf-8") as file:
            json.dump(bank, file, ensure_ascii=False, indent=4)
        temp_path.replace(path)

    def _records_from_bank(self, bank):
        records = []
        for item in bank.get("memories", []):
            if item.get("category") == "reflection" and "base_memories" in item:
                record = ReflectionRecord.from_dict(item)
            else:
                record = MemoryRecord.from_dict(item)
            record.agent_name = record.agent_name or bank.get("agent_name")
            records.append(record)
        return records

    def _load_records(self, agent_name=None):
        if agent_name:
            return self._records_from_bank(self._load_bank(agent_name))

        records = []
        for path in self.memory_dir.glob("*.json"):
            with path.open("r", encoding="utf-8") as file:
                records.extend(self._records_from_bank(json.load(file)))
        return self._prune_records(records)

    def _prune_records(self, records):
        min_life_day = self.current_life_day - self.retention_days + 1
        return [
            record for record in records
            if record.life_day is None or int(record.life_day) >= min_life_day
        ]

    def _refresh_cache(self, agent_names=None):
        if agent_names:
            records = []
            for agent_name in agent_names:
                records.extend(self._records_from_bank(self._load_bank(agent_name)))
            self.memories = self._prune_records(records)
        else:
            self.memories = self._load_records()
