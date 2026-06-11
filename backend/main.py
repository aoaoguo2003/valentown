from flask import Flask, jsonify, request
from agents.agent import RonParker, EllaParker, EmmaHarris, GavinHarris, AdamHarris, MiaThompson, ArthurMorgan
from memory.memory_system import MemorySystem
from memory.reflection import Reflection
from agent_state import (
    advance_agent_state_time,
    complete_agent_action,
    ensure_agent_state_files,
    evaluate_agent_triggers,
    load_agent_state,
    load_all_agent_states,
    update_agent_state
)
from config import USE_CACHED_DAILY_PLANS
import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
LIFE_PLANS_FILE = BASE_DIR / "life_plans.json"
PROGRESS_FILE = BASE_DIR / "simulation_progress.json"

try:
    from flask_cors import CORS
except ImportError:
    CORS = None

app = Flask(__name__)
if CORS:
    CORS(app)  # 允许所有域名访问后端
else:
    @app.after_request
    def add_cors_headers(response):
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        return response

# 创建记忆系统实例（内存持久化支持已在 MemorySystem 中实现）
memory_system = MemorySystem(retention_days=15)

# 创建所有代理，并为它们指定不同的初始位置
agents = [
    RonParker(memory_system, "Valentown Supermarket"),
    EllaParker(memory_system, "Valentown Library"),
    EmmaHarris(memory_system, "Valentown Cafe"),
    GavinHarris(memory_system, "Valentown Park"),
    AdamHarris(memory_system, "Valentown Office"),
    MiaThompson(memory_system, "Valentown School"),
    ArthurMorgan(memory_system, "Valentown Town Hall")
]
agent_names = [agent.name for agent in agents]
ensure_agent_state_files(agent_names)
memory_system.initialize_agents(agent_names)

# 创建一个字典来存储每天每个代理的计划
daily_plans = {}
simulation_progress = {
    "current_life_day": 1,
    "current_time_minutes": 6 * 60,
    "status": "ready",
    "agent_locations": {},
    "agent_positions": {},
    "agent_pose_states": {}
}

def load_simulation_progress():
    if not PROGRESS_FILE.exists():
        return dict(simulation_progress)

    with PROGRESS_FILE.open("r", encoding="utf-8") as file:
        loaded = json.load(file)

    progress = dict(simulation_progress)
    progress.update(loaded)
    progress["current_life_day"] = max(1, int(progress.get("current_life_day", 1)))
    progress["current_time_minutes"] = max(0, int(progress.get("current_time_minutes", 6 * 60)))
    progress["agent_locations"] = progress.get("agent_locations") if isinstance(progress.get("agent_locations"), dict) else {}
    progress["agent_positions"] = progress.get("agent_positions") if isinstance(progress.get("agent_positions"), dict) else {}
    progress["agent_pose_states"] = progress.get("agent_pose_states") if isinstance(progress.get("agent_pose_states"), dict) else {}
    return progress

def save_simulation_progress(progress=None):
    data = dict(simulation_progress)
    if progress:
        data.update(progress)
    data["current_life_day"] = max(1, int(data.get("current_life_day", 1)))
    data["current_time_minutes"] = max(0, int(data.get("current_time_minutes", 6 * 60)))
    data["agent_locations"] = data.get("agent_locations") if isinstance(data.get("agent_locations"), dict) else {}
    data["agent_positions"] = data.get("agent_positions") if isinstance(data.get("agent_positions"), dict) else {}
    data["agent_pose_states"] = data.get("agent_pose_states") if isinstance(data.get("agent_pose_states"), dict) else {}
    with PROGRESS_FILE.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=4)
    simulation_progress.update(data)
    memory_system.set_life_day(data["current_life_day"], agent_names)
    return data

def load_life_plans(filename=LIFE_PLANS_FILE):
    global daily_plans

    path = Path(filename)
    if not path.exists():
        return False

    with path.open("r", encoding="utf-8") as f:
        raw_plans = json.load(f)

    daily_plans = {int(day): plan for day, plan in raw_plans.items()}
    print(f"Loaded {len(daily_plans)} lived-day plans from {filename}.")
    return True

simulation_progress.update(load_simulation_progress())
memory_system.set_life_day(simulation_progress["current_life_day"], agent_names)
load_life_plans()

def ensure_life_day_plan(life_day):
    life_day = max(1, int(life_day or 1))
    load_life_plans()
    if life_day in daily_plans and all(agent.name in daily_plans[life_day] for agent in agents):
        memory_system.set_life_day(life_day, agent_names)
        save_simulation_progress({"current_life_day": life_day})
        return

    memory_system.set_life_day(life_day, agent_names)
    print(f"\n========== Generating lived day {life_day} ==========")

    if life_day > 1:
        for agent in agents:
            reflection_obj = Reflection(memory_system, agent.name)
            reflection_obj.generate_reflection(life_day=life_day)

    day_plan = {}
    location_agents = {}

    for agent in agents:
        plan, destination = agent.generate_daily_plan(day_number=life_day)
        if not plan or not destination:
            raise RuntimeError(f"Failed to generate daily plan for {agent.name} using Claude.")

        day_plan[agent.name] = [plan, destination]
        agent.current_location = destination
        big_location = destination.split('.')[0]
        location_agents.setdefault(big_location, []).append(agent)

    conversations = []
    for big_loc, loc_agents in location_agents.items():
        if len(loc_agents) < 2:
            continue

        processed_pairs = set()
        sorted_agents = sorted(loc_agents, key=lambda x: -x.age)
        for speaker in sorted_agents:
            available_agents = [
                agent for agent in sorted_agents
                if agent != speaker
                and (speaker.name, agent.name) not in processed_pairs
                and (agent.name, speaker.name) not in processed_pairs
            ]
            if not available_agents:
                continue

            conversation = speaker.start_communicate(
                other_agents=available_agents,
                current_location=big_loc,
                day_number=life_day
            )
            if conversation:
                conversations.append(conversation)
                processed_pairs.add((conversation["initiator"], conversation["responder"]))

    day_plan["conversations"] = conversations
    daily_plans[life_day] = day_plan

    with LIFE_PLANS_FILE.open("w", encoding="utf-8") as file:
        json.dump(daily_plans, file, ensure_ascii=False, indent=4)

    memory_system.save_to_file(BASE_DIR / "memory_data.json")
    save_simulation_progress({"current_life_day": life_day})


# 创建一个API端点返回每日计划
@app.route('/get_daily_plan', methods=['GET'])
def get_daily_plan():
    agent_name = request.args.get('agent_name')
    try:
        life_day = int(request.args.get('life_day') or request.args.get('day') or simulation_progress.get('current_life_day', 1))
    except ValueError:
        return jsonify({"error": "life_day must be a number"}), 400

    if not agent_name:
        return jsonify({"error": "agent_name is required"}), 400

    try:
        ensure_life_day_plan(life_day)
    except RuntimeError as error:
        return jsonify({"error": "Claude generation failed", "details": str(error)}), 503

    if agent_name not in daily_plans.get(life_day, {}):
        return jsonify({"error": "Agent not found for the requested lived day"}), 404

    return jsonify({
        "agent_name": agent_name,
        "life_day": life_day,
        "daily_plan": daily_plans[life_day][agent_name]
    })

@app.route('/get_conversations', methods=['GET'])
def get_conversations():
    try:
        life_day = int(request.args.get('life_day') or request.args.get('day') or simulation_progress.get('current_life_day', 1))
    except ValueError:
        return jsonify({"error": "life_day must be a number"}), 400

    try:
        ensure_life_day_plan(life_day)
    except RuntimeError as error:
        return jsonify({"error": "Claude generation failed", "details": str(error)}), 503

    convos = daily_plans.get(life_day, {}).get("conversations", [])
    location = request.args.get('location')
    if location:
        convos = [conversation for conversation in convos if conversation["location"] == location]

    return jsonify({
        "life_day": life_day,
        "count": len(convos),
        "conversations": convos
    })

@app.route('/get_config', methods=['GET'])
def get_config():
    return jsonify({
        "agents": agent_names,
        "current_life_day": simulation_progress.get("current_life_day", 1),
        "current_time_minutes": simulation_progress.get("current_time_minutes", 6 * 60),
        "status": simulation_progress.get("status", "ready"),
        "agent_locations": simulation_progress.get("agent_locations", {}),
        "agent_positions": simulation_progress.get("agent_positions", {}),
        "agent_pose_states": simulation_progress.get("agent_pose_states", {}),
        "retention_days": memory_system.retention_days
    })

@app.route('/get_simulation_progress', methods=['GET'])
def get_simulation_progress():
    return jsonify(save_simulation_progress())

@app.route('/update_simulation_progress', methods=['POST'])
def update_simulation_progress():
    data = request.get_json(silent=True) or {}
    updates = {}
    if "current_life_day" in data:
        updates["current_life_day"] = data["current_life_day"]
    if "current_time_minutes" in data:
        updates["current_time_minutes"] = data["current_time_minutes"]
    if "status" in data:
        updates["status"] = data["status"]
    if "agent_locations" in data and isinstance(data["agent_locations"], dict):
        updates["agent_locations"] = data["agent_locations"]
    if "agent_positions" in data and isinstance(data["agent_positions"], dict):
        updates["agent_positions"] = data["agent_positions"]
    if "agent_pose_states" in data and isinstance(data["agent_pose_states"], dict):
        updates["agent_pose_states"] = data["agent_pose_states"]
    return jsonify(save_simulation_progress(updates))

@app.route('/get_agent_internal_states', methods=['GET'])
def get_agent_internal_states():
    states = load_all_agent_states(agent_names)
    return jsonify({
        "count": len(states),
        "states": states
    })

@app.route('/get_agent_internal_state', methods=['GET'])
def get_agent_internal_state():
    agent_name = request.args.get('agent_name')
    if not agent_name:
        return jsonify({"error": "agent_name is required"}), 400
    if agent_name not in agent_names:
        return jsonify({"error": "Unknown agent"}), 404

    state = load_agent_state(agent_name)
    return jsonify({
        "agent_name": agent_name,
        "state": state,
        "triggers": evaluate_agent_triggers(state)
    })

@app.route('/get_agent_memories', methods=['GET'])
def get_agent_memories():
    agent_name = request.args.get('agent_name')
    if not agent_name:
        return jsonify({"error": "agent_name is required"}), 400
    if agent_name not in agent_names:
        return jsonify({"error": "Unknown agent"}), 404

    bank = memory_system.get_agent_memory_bank(agent_name)
    return jsonify({
        "agent_name": agent_name,
        "retention_days": bank["retention_days"],
        "current_life_day": bank["current_life_day"],
        "count": len(bank["memories"]),
        "memories": bank["memories"]
    })

@app.route('/get_all_agent_memories', methods=['GET'])
def get_all_agent_memories():
    banks = {agent_name: memory_system.get_agent_memory_bank(agent_name) for agent_name in agent_names}
    return jsonify({
        "retention_days": memory_system.retention_days,
        "current_life_day": memory_system.current_life_day,
        "agents": banks
    })

@app.route('/update_agent_internal_state', methods=['POST'])
def update_agent_internal_state():
    data = request.get_json(silent=True) or {}
    agent_name = data.get("agent_name")
    if not agent_name:
        return jsonify({"error": "agent_name is required"}), 400
    if agent_name not in agent_names:
        return jsonify({"error": "Unknown agent"}), 404

    state = update_agent_state(
        agent_name,
        {
            "values": data.get("values", {}),
            "thresholds": data.get("thresholds", {})
        },
        day=data.get("day"),
        time=data.get("time")
    )
    return jsonify({
        "agent_name": agent_name,
        "state": state,
        "triggers": evaluate_agent_triggers(state)
    })

# 为根路径添加路由
@app.route('/advance_agent_internal_state', methods=['POST'])
def advance_agent_internal_state():
    data = request.get_json(silent=True) or {}
    agent_name = data.get("agent_name")
    if not agent_name:
        return jsonify({"error": "agent_name is required"}), 400
    if agent_name not in agent_names:
        return jsonify({"error": "Unknown agent"}), 404

    state = advance_agent_state_time(
        agent_name,
        elapsed_game_minutes=data.get("elapsed_game_minutes", 0),
        day=data.get("day"),
        time=data.get("time"),
        sleeping=bool(data.get("sleeping", False)),
        social_contact=bool(data.get("social_contact", False))
    )
    return jsonify({
        "agent_name": agent_name,
        "state": state,
        "triggers": evaluate_agent_triggers(state)
    })

@app.route('/complete_agent_action', methods=['POST'])
def complete_agent_action_route():
    data = request.get_json(silent=True) or {}
    agent_name = data.get("agent_name")
    if not agent_name:
        return jsonify({"error": "agent_name is required"}), 400
    if agent_name not in agent_names:
        return jsonify({"error": "Unknown agent"}), 404

    state, effects = complete_agent_action(
        agent_name,
        location_name=data.get("location", ""),
        action_text=data.get("action", ""),
        elapsed_game_minutes=data.get("elapsed_game_minutes", 0),
        day=data.get("day"),
        time=data.get("time"),
        sleeping=bool(data.get("sleeping", False)),
        social_contact=bool(data.get("social_contact", False))
    )
    return jsonify({
        "agent_name": agent_name,
        "state": state,
        "effects": effects,
        "triggers": evaluate_agent_triggers(state)
    })

@app.route('/')
def home():
    return "Welcome to Valentown!"

# 处理 favicon.ico 请求
@app.route('/favicon.ico')
def favicon():
    return '', 204  # 返回空响应，表示成功处理了请求

# 启动 Flask
if __name__ == "__main__":
    app.run(debug=False, host='0.0.0.0', port=5000, use_reloader=False)
