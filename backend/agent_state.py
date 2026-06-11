import json
import re
from copy import deepcopy
from pathlib import Path


STATE_DIR = Path(__file__).with_name("agent_internal_states")
DEFAULT_DAY = 1
DEFAULT_TIME = "6:00 AM"
MINUTES_PER_DAY = 24 * 60

DEFAULT_STATE = {
    "version": 2,
    "agent_name": "",
    "values": {
        "hunger": 35,
        "energy": 75,
        "social": 55
    },
    "thresholds": {
        "hunger_seek_food_at": 75,
        "energy_sleep_at_or_below": 25,
        "social_seek_friend_at_or_below": 30
    },
    "rates_per_game_hour": {
        "hunger_increase": 8,
        "energy_decrease_awake": 6,
        "energy_recover_sleep": 18,
        "social_decrease": 4
    },
    "trigger_preferences": {
        "hunger": {
            "intent": "seek_food",
            "priority": 80,
            "preferred_location_types": ["own_home.Kitchen", "own_home.Dining_table", "Cafe.Counter"],
            "example_action": "find something to eat"
        },
        "energy": {
            "intent": "sleep_or_rest",
            "priority": 90,
            "preferred_location_types": ["own_home.Bed", "own_home.Sofa"],
            "example_action": "rest until energy recovers"
        },
        "social": {
            "intent": "seek_friend",
            "priority": 65,
            "preferred_location_types": ["friend_location", "Park.Bench", "Cafe.Window_seat"],
            "example_action": "find someone to talk to"
        }
    },
    "last_updated": {
        "day": DEFAULT_DAY,
        "time": DEFAULT_TIME,
        "game_minute": 6 * 60
    },
    "time_anchors": {}
}

FOOD_LOCATION_TOKENS = (
    "kitchen",
    "dining",
    "dinning",
    "cafe",
    "café",
    "counter",
    "customer_cafe",
    "customer_eat",
    "bar",
    "patio"
)

FOOD_ACTION_TOKENS = (
    "eat",
    "meal",
    "food",
    "breakfast",
    "lunch",
    "dinner",
    "cook",
    "coffee"
)

SOCIAL_ACTION_TOKENS = (
    "chat",
    "talk",
    "conversation",
    "greet",
    "visit",
    "social"
)

SLEEP_ACTION_TOKENS = (
    "sleep",
    "wake",
    "wake up",
    "nap",
    "rest"
)

AGENT_INITIAL_OVERRIDES = {
    "Ron Parker": {
        "values": {"hunger": 30, "energy": 68, "social": 62},
        "thresholds": {"energy_sleep_at_or_below": 28}
    },
    "Ella Parker": {
        "values": {"hunger": 28, "energy": 70, "social": 52},
        "thresholds": {"hunger_seek_food_at": 72}
    },
    "Emma Harris": {
        "values": {"hunger": 32, "energy": 74, "social": 58},
        "thresholds": {"social_seek_friend_at_or_below": 35}
    },
    "Gavin Harris": {
        "values": {"hunger": 38, "energy": 78, "social": 50},
        "thresholds": {"hunger_seek_food_at": 78}
    },
    "Adam Harris": {
        "values": {"hunger": 45, "energy": 86, "social": 70},
        "thresholds": {"hunger_seek_food_at": 68, "energy_sleep_at_or_below": 20}
    },
    "Mia Thompson": {
        "values": {"hunger": 33, "energy": 76, "social": 61},
        "thresholds": {"social_seek_friend_at_or_below": 38}
    },
    "Arthur Morgan": {
        "values": {"hunger": 30, "energy": 72, "social": 42},
        "thresholds": {"social_seek_friend_at_or_below": 24}
    }
}


def agent_state_filename(agent_name):
    return agent_name.lower().replace(" ", "_") + ".json"


def agent_state_path(agent_name):
    return STATE_DIR / agent_state_filename(agent_name)


def merge_dict(base, override):
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_dict(merged[key], value)
        else:
            merged[key] = value
    return merged


def build_default_agent_state(agent_name):
    state = deepcopy(DEFAULT_STATE)
    state["agent_name"] = agent_name
    return initialize_time_anchors(merge_dict(state, AGENT_INITIAL_OVERRIDES.get(agent_name, {})))


def ensure_agent_state_files(agent_names):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    for agent_name in agent_names:
        path = agent_state_path(agent_name)
        if not path.exists():
            save_agent_state(agent_name, build_default_agent_state(agent_name))
        else:
            state = load_agent_state(agent_name)
            save_agent_state(agent_name, state)


def load_agent_state(agent_name):
    path = agent_state_path(agent_name)
    if not path.exists():
        state = build_default_agent_state(agent_name)
        save_agent_state(agent_name, state)
        return state

    with path.open("r", encoding="utf-8") as file:
        state = json.load(file)

    merged = merge_dict(build_default_agent_state(agent_name), state)
    merged["agent_name"] = agent_name
    merged["version"] = DEFAULT_STATE["version"]
    return sanitize_legacy_action(initialize_time_anchors(merged))


def save_agent_state(agent_name, state):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with agent_state_path(agent_name).open("w", encoding="utf-8") as file:
        json.dump(state, file, ensure_ascii=False, indent=4)


def load_all_agent_states(agent_names):
    ensure_agent_state_files(agent_names)
    return {agent_name: load_agent_state(agent_name) for agent_name in agent_names}


def clamp_state_values(state):
    for key, value in state.get("values", {}).items():
        state["values"][key] = max(0, min(100, int(round(value))))
    return state


def parse_clock_to_minutes(clock_text):
    match = re.match(r"^\s*(\d{1,2})(?::(\d{2}))?\s*(AM|PM)\s*$", str(clock_text or ""), re.I)
    if not match:
        return 6 * 60

    hours = int(match.group(1))
    minutes = int(match.group(2) or 0)
    period = match.group(3).upper()
    if period == "PM" and hours != 12:
        hours += 12
    if period == "AM" and hours == 12:
        hours = 0
    return (hours * 60) + minutes


def to_game_minute(day=None, time=None, fallback=6 * 60):
    if day is None and time is None:
        return int(fallback)

    day_number = int(day or DEFAULT_DAY)
    return ((day_number - 1) * MINUTES_PER_DAY) + parse_clock_to_minutes(time or DEFAULT_TIME)


def get_current_game_minute(state, elapsed_game_minutes=0, day=None, time=None):
    last_updated = state.get("last_updated", {})
    fallback = last_updated.get("game_minute", to_game_minute(last_updated.get("day"), last_updated.get("time")))
    if day is not None or time is not None:
        return to_game_minute(day, time, fallback)
    return int(fallback) + max(0, int(round(float(elapsed_game_minutes or 0))))


def initialize_time_anchors(state):
    values = state.setdefault("values", {})
    rates = state.setdefault("rates_per_game_hour", DEFAULT_STATE["rates_per_game_hour"])
    last_updated = state.setdefault("last_updated", deepcopy(DEFAULT_STATE["last_updated"]))
    current_game_minute = last_updated.get("game_minute")
    if current_game_minute is None:
        current_game_minute = to_game_minute(last_updated.get("day"), last_updated.get("time"))
        last_updated["game_minute"] = current_game_minute

    anchors = state.setdefault("time_anchors", {})

    if anchors.get("last_meal_game_minute") is None:
        hunger_rate = max(0.1, rates.get("hunger_increase", 8))
        anchors["last_meal_game_minute"] = current_game_minute - ((values.get("hunger", 0) / hunger_rate) * 60)

    if anchors.get("last_social_game_minute") is None:
        social_rate = max(0.1, rates.get("social_decrease", 4))
        anchors["last_social_game_minute"] = current_game_minute - (((100 - values.get("social", 100)) / social_rate) * 60)

    if anchors.get("last_sleep_game_minute") is None:
        energy_rate = max(0.1, rates.get("energy_decrease_awake", 6))
        anchors["last_sleep_game_minute"] = current_game_minute - (((100 - values.get("energy", 100)) / energy_rate) * 60)

    return clamp_state_values(state)


def sanitize_legacy_action(state):
    last_action = state.get("last_action")
    if not isinstance(last_action, dict):
        return state

    action = str(last_action.get("action", ""))
    if action and not all((32 <= ord(char) <= 126) for char in action):
        last_action["action"] = "legacy action"
    return state


def recalculate_values_from_anchors(state, current_game_minute):
    values = state.setdefault("values", {})
    rates = state.get("rates_per_game_hour", {})
    anchors = state.setdefault("time_anchors", {})

    last_meal = anchors.get("last_meal_game_minute", current_game_minute)
    last_social = anchors.get("last_social_game_minute", current_game_minute)
    last_sleep = anchors.get("last_sleep_game_minute", current_game_minute)

    values["hunger"] = ((current_game_minute - last_meal) / 60) * rates.get("hunger_increase", 8)
    values["social"] = 100 - (((current_game_minute - last_social) / 60) * rates.get("social_decrease", 4))
    values["energy"] = 100 - (((current_game_minute - last_sleep) / 60) * rates.get("energy_decrease_awake", 6))

    return clamp_state_values(state)


def mark_state_time(state, day=None, time=None, current_game_minute=None):
    state.setdefault("last_updated", {})
    if day is not None:
        state["last_updated"]["day"] = int(day)
    if time is not None:
        state["last_updated"]["time"] = str(time)
    if current_game_minute is not None:
        state["last_updated"]["game_minute"] = int(round(current_game_minute))


def contains_token(location_name="", action_text="", tokens=()):
    source = f"{location_name or ''} {action_text or ''}".lower()
    return any(token.lower() in source for token in tokens)


def is_food_location(location_name="", action_text=""):
    return contains_token(location_name, action_text, FOOD_LOCATION_TOKENS + FOOD_ACTION_TOKENS)


def is_social_action(location_name="", action_text=""):
    return contains_token(location_name, action_text, SOCIAL_ACTION_TOKENS)


def is_sleep_action(location_name="", action_text=""):
    return contains_token(location_name, action_text, SLEEP_ACTION_TOKENS) or "bed" in str(location_name or "").lower()


def evaluate_agent_triggers(state):
    values = state.get("values", {})
    thresholds = state.get("thresholds", {})
    preferences = state.get("trigger_preferences", {})
    triggers = []

    if values.get("hunger", 0) >= thresholds.get("hunger_seek_food_at", 75):
        triggers.append({
            "need": "hunger",
            "intent": preferences["hunger"]["intent"],
            "priority": preferences["hunger"]["priority"],
            "reason": "hunger is high enough to seek food",
            "preferred_location_types": preferences["hunger"]["preferred_location_types"],
            "example_action": preferences["hunger"]["example_action"]
        })

    if values.get("energy", 100) <= thresholds.get("energy_sleep_at_or_below", 25):
        triggers.append({
            "need": "energy",
            "intent": preferences["energy"]["intent"],
            "priority": preferences["energy"]["priority"],
            "reason": "energy is low enough to rest or sleep",
            "preferred_location_types": preferences["energy"]["preferred_location_types"],
            "example_action": preferences["energy"]["example_action"]
        })

    if values.get("social", 100) <= thresholds.get("social_seek_friend_at_or_below", 30):
        triggers.append({
            "need": "social",
            "intent": preferences["social"]["intent"],
            "priority": preferences["social"]["priority"],
            "reason": "social need is low enough to seek a friend",
            "preferred_location_types": preferences["social"]["preferred_location_types"],
            "example_action": preferences["social"]["example_action"]
        })

    return sorted(triggers, key=lambda item: item["priority"], reverse=True)


def update_agent_state(agent_name, updates, day=None, time=None):
    state = load_agent_state(agent_name)
    values = updates.get("values", {})
    thresholds = updates.get("thresholds", {})

    state.setdefault("values", {}).update(values)
    state.setdefault("thresholds", {}).update(thresholds)
    current_game_minute = get_current_game_minute(state, day=day, time=time)
    mark_state_time(state, day=day, time=time, current_game_minute=current_game_minute)

    # Rebuild anchors from explicit values so manual edits become the new baseline.
    state["time_anchors"] = {}
    initialize_time_anchors(state)
    clamp_state_values(state)
    save_agent_state(agent_name, state)
    return state


def advance_agent_state_time(agent_name, elapsed_game_minutes=0, day=None, time=None, sleeping=False, social_contact=False):
    state = load_agent_state(agent_name)
    current_game_minute = get_current_game_minute(state, elapsed_game_minutes=elapsed_game_minutes, day=day, time=time)
    anchors = state.setdefault("time_anchors", {})

    if social_contact:
        anchors["last_social_game_minute"] = current_game_minute
    if sleeping:
        anchors["last_sleep_game_minute"] = current_game_minute

    recalculate_values_from_anchors(state, current_game_minute)
    mark_state_time(state, day=day, time=time, current_game_minute=current_game_minute)
    save_agent_state(agent_name, state)
    return state


def complete_agent_action(agent_name, location_name="", action_text="", elapsed_game_minutes=0, day=None, time=None, sleeping=False, social_contact=False):
    state = load_agent_state(agent_name)
    current_game_minute = get_current_game_minute(state, elapsed_game_minutes=elapsed_game_minutes, day=day, time=time)
    anchors = state.setdefault("time_anchors", {})
    effects = []

    if is_food_location(location_name, action_text):
        anchors["last_meal_game_minute"] = current_game_minute
        effects.append("hunger_reset")

    if social_contact or is_social_action(location_name, action_text):
        anchors["last_social_game_minute"] = current_game_minute
        effects.append("social_reset")

    if sleeping or is_sleep_action(location_name, action_text):
        anchors["last_sleep_game_minute"] = current_game_minute
        effects.append("energy_reset")

    recalculate_values_from_anchors(state, current_game_minute)
    mark_state_time(state, day=day, time=time, current_game_minute=current_game_minute)

    state["last_action"] = {
        "location": location_name,
        "action": action_text,
        "day": day,
        "time": time,
        "game_minute": int(round(current_game_minute)),
        "elapsed_game_minutes": max(0, int(round(float(elapsed_game_minutes or 0)))),
        "effects": effects
    }

    clamp_state_values(state)
    save_agent_state(agent_name, state)
    return state, effects
