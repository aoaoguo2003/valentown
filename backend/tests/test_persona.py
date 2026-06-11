"""Unit tests for the per-agent persona store (offline, no LLM)."""

from memory.persona_store import PersonaStore


def test_get_returns_none_when_unset(tmp_path):
    store = PersonaStore(persona_dir=tmp_path)
    assert store.get("Ron Parker") is None


def test_set_then_get_roundtrip_and_persists(tmp_path):
    store = PersonaStore(persona_dir=tmp_path)
    store.set("Ron Parker", "  Ron is a warm shopkeeper who values his customers.  ", life_day=3)
    assert store.get("Ron Parker") == "Ron is a warm shopkeeper who values his customers."

    # A fresh store over the same directory reads the persisted value.
    reopened = PersonaStore(persona_dir=tmp_path)
    assert reopened.get("Ron Parker") == "Ron is a warm shopkeeper who values his customers."


def test_set_overwrites_previous_persona(tmp_path):
    store = PersonaStore(persona_dir=tmp_path)
    store.set("Mia Thompson", "Mia keeps to herself.", life_day=2)
    store.set("Mia Thompson", "Mia has started opening up to neighbours.", life_day=5)
    assert store.get("Mia Thompson") == "Mia has started opening up to neighbours."


def test_empty_persona_is_ignored(tmp_path):
    store = PersonaStore(persona_dir=tmp_path)
    store.set("Arthur Morgan", "   ", life_day=4)
    assert store.get("Arthur Morgan") is None


def test_agents_are_isolated(tmp_path):
    store = PersonaStore(persona_dir=tmp_path)
    store.set("Ron Parker", "Ron is cheerful.", life_day=1)
    store.set("Ella Parker", "Ella is meticulous.", life_day=1)
    assert store.get("Ron Parker") == "Ron is cheerful."
    assert store.get("Ella Parker") == "Ella is meticulous."
