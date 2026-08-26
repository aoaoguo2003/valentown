from flask import Flask, jsonify, request
from agents.agent import RonParker, EllaParker, EmmaHarris, GavinHarris, AdamHarris, MiaThompson, ArthurMorgan
from memory.memory_system import MemorySystem
from memory.persona_store import persona_store
from memory.reflection import Reflection
from agents.state import (
    parse_clock_to_minutes,
    advance_agent_state_time,
    complete_agent_action,
    ensure_agent_state_files,
    evaluate_agent_triggers,
    load_agent_state,
    load_all_agent_states,
    update_agent_state
)
from runtime import run_decision_loop
import world.events as events
from world.economy import economy
from world.goals import goal_store
from world.mailbox import mailbox
from world.weather import weather_service
from world.snapshot import snapshot
import json
import threading
from pathlib import Path

# 存档留在 backend/ 根目录下——这个文件下沉进 api/ 之后，
# 自己的目录已经不是它们该待的地方了。
BASE_DIR = Path(__file__).resolve().parent.parent
PROGRESS_FILE = BASE_DIR / "simulation_progress.json"
CONVERSATIONS_FILE = BASE_DIR / "conversations.json"

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
    RonParker(memory_system, "Ron_home.Living_room"),
    EllaParker(memory_system, "Ella_home.Living_room"),
    EmmaHarris(memory_system, "Emma_home.Living_room"),
    GavinHarris(memory_system, "Gavin_home.Living_room"),
    AdamHarris(memory_system, "Adam_home.Living_room"),
    MiaThompson(memory_system, "Mia_home.Living_room"),
    ArthurMorgan(memory_system, "Arthur_home.Living_room")
]
agents_by_name = {agent.name: agent for agent in agents}
agent_names = [agent.name for agent in agents]
ensure_agent_state_files(agent_names)
memory_system.initialize_agents(agent_names)

# 用于序列化多个请求可能并发访问的共享状态
state_lock = threading.Lock()

simulation_progress = {
    "current_life_day": 1,
    "current_time_minutes": 6 * 60,
    "status": "ready",
    "agent_locations": {},
    "agent_positions": {},
    "agent_pose_states": {}
}

# 按生活日累积的对话记录
conversations_by_day = {}


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


def load_conversations():
    global conversations_by_day
    if not CONVERSATIONS_FILE.exists():
        return

    try:
        with CONVERSATIONS_FILE.open("r", encoding="utf-8") as file:
            raw = json.load(file)
        conversations_by_day = {int(day): convos for day, convos in raw.items()}
    except (json.JSONDecodeError, ValueError):
        conversations_by_day = {}


def save_conversations():
    with CONVERSATIONS_FILE.open("w", encoding="utf-8") as file:
        json.dump(conversations_by_day, file, ensure_ascii=False, indent=4)


simulation_progress.update(load_simulation_progress())
memory_system.set_life_day(simulation_progress["current_life_day"], agent_names)
load_conversations()


def current_agent_locations():
    """世界眼中"每个人现在在哪"：以后端记录的目的地为底，再用前端同步
    上来的实际位置覆盖。调用方需持有 state_lock。

    ⚠️ 这是**世界视角**的全局位置表。它只用于裁决动作和构造感知结果，
    绝不能整份进入任何居民的决策上下文——居民只能看见同区域的人。
    """
    locations = {agent.name: agent.current_location for agent in agents}
    for name, location in (simulation_progress.get("agent_locations") or {}).items():
        if name in locations and location:
            locations[name] = location
    return locations


def make_world_provider(time_text, life_day):
    """交给决策循环的 ``with_world``：在锁内取最新世界快照并调用 fn。

    锁只在这一瞬间持有（构造快照 + 裁决，都是纯内存操作，微秒级），
    循环里的 LLM 调用全部发生在锁外。改造前整个决策——包括那次最长
    60 秒的网络请求——都在锁内，七个居民因此彻底串行。
    """
    # 天气在进锁之前预热：它背后是一次外部调用（虽然有缓存），绝不能把一次
    # 可能的网络往返塞进临界区里。预热之后 snapshot() 里那次取值只读缓存。
    weather_service.at(life_day, parse_clock_to_minutes(time_text))
    # 事件要盖时间戳，而世界服务不知道现在几点。headless 调度器里
    # 也有同样一行——两条路径在这件事上必须一致。
    events.event_log.set_clock(life_day, parse_clock_to_minutes(time_text))

    def with_world(fn):
        with state_lock:
            return fn(snapshot(
                agent_locations=current_agent_locations(),
                time_text=time_text,
                life_day=life_day,
            ))
    return with_world


@app.route('/decide_next_action', methods=['POST'])
def decide_next_action():
    """基于需求驱动的规划：每当某个代理完成一个动作、需要决定接下来
    做什么时，客户端就会调用这个接口。"""
    data = request.get_json(silent=True) or {}
    agent_name = data.get("agent_name")
    if not agent_name:
        return jsonify({"error": "agent_name is required"}), 400
    if agent_name not in agents_by_name:
        return jsonify({"error": "Unknown agent"}), 404

    try:
        life_day = max(1, int(data.get("day") or simulation_progress.get("current_life_day", 1)))
    except (TypeError, ValueError):
        return jsonify({"error": "day must be a number"}), 400

    agent = agents_by_name[agent_name]
    state = load_agent_state(agent_name)
    triggers = evaluate_agent_triggers(state)
    time_text = data.get("time") or "morning"

    with state_lock:
        memory_system.set_life_day(life_day, [agent_name])

    # 多步决策循环：模型自己选工具，环境可以拒绝，被拒后带着理由重新规划。
    # LLM 调用在锁外，只有取快照和提交决策进锁。
    decision, steps = run_decision_loop(
        agent,
        internal_state=state,
        triggers=triggers,
        day_number=life_day,
        time_text=time_text,
        current_location=data.get("current_location") or agent.current_location,
        last_action=data.get("last_action"),
        with_world=make_world_provider(time_text, life_day),
    )

    # 响应只增字段不改字段：decision 的结构与改造前一致，前端无需改动。
    return jsonify({
        "agent_name": agent_name,
        "life_day": life_day,
        "decision": decision,
        "triggers": triggers,
        "observation": agent.last_observation,
        "steps": steps
    })


@app.route('/generate_conversation', methods=['POST'])
def generate_conversation():
    """为处于同一地点的两个代理生成一段简短对话，并将其存入
    按天记录的对话日志中。"""
    data = request.get_json(silent=True) or {}
    initiator_name = data.get("initiator")
    responder_name = data.get("responder")
    if not initiator_name or not responder_name:
        return jsonify({"error": "initiator and responder are required"}), 400
    if initiator_name not in agents_by_name or responder_name not in agents_by_name:
        return jsonify({"error": "Unknown agent"}), 404
    if initiator_name == responder_name:
        return jsonify({"error": "initiator and responder must differ"}), 400

    try:
        life_day = max(1, int(data.get("day") or simulation_progress.get("current_life_day", 1)))
    except (TypeError, ValueError):
        return jsonify({"error": "day must be a number"}), 400

    location = data.get("location") or "Valentown"
    initiator = agents_by_name[initiator_name]
    responder = agents_by_name[responder_name]

    with state_lock:
        conversation = initiator.talk_with(responder, life_day, location)
        if conversation:
            conversations_by_day.setdefault(life_day, []).append(conversation)
            save_conversations()

    if not conversation:
        return jsonify({"error": "LLM conversation generation failed"}), 503

    return jsonify({
        "life_day": life_day,
        "conversation": conversation
    })


@app.route('/start_new_day', methods=['POST'])
def start_new_day():
    """将模拟推进到新的一天：持久化进度，并让每个代理
    对前一天的记忆进行反思。"""
    data = request.get_json(silent=True) or {}
    try:
        life_day = max(1, int(data.get("life_day") or simulation_progress.get("current_life_day", 1)))
    except (TypeError, ValueError):
        return jsonify({"error": "life_day must be a number"}), 400

    reflections = {}
    with state_lock:
        memory_system.set_life_day(life_day, agent_names)
        save_simulation_progress({"current_life_day": life_day})
        # 每日进货：货架补回上限。补满而非累加，否则卖不掉的东西会
        # 无限堆积，几天之后稀缺性就消失了，抢购也就不会再发生。
        economy.restock_daily()
        # 每三天发一次社保。注意这两个操作的性质不同：补货是赋值，重复
        # 调用无害；发钱是累加，重复调用钱就翻倍——所以它用天数当幂等键，
        # 自己记住"这一天发过了"。
        economy.pay_benefit(life_day, agent_names)

        if life_day > 1:
            for agent in agents:
                reflection_obj = Reflection(memory_system, agent.name)
                _, answer = reflection_obj.generate_reflection(life_day=life_day)
                reflections[agent.name] = bool(answer)

    return jsonify({
        "life_day": life_day,
        "reflections_generated": reflections
    })


@app.route('/get_conversations', methods=['GET'])
def get_conversations():
    try:
        life_day = int(request.args.get('life_day') or request.args.get('day') or simulation_progress.get('current_life_day', 1))
    except ValueError:
        return jsonify({"error": "life_day must be a number"}), 400

    convos = conversations_by_day.get(life_day, [])
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
    # 只读接口：GET 请求不应写入磁盘或修改共享状态
    return jsonify(dict(simulation_progress))


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
    with state_lock:
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


@app.route('/get_agent_persona', methods=['GET'])
def get_agent_persona():
    agent_name = request.args.get('agent_name')
    if not agent_name:
        return jsonify({"error": "agent_name is required"}), 400
    if agent_name not in agent_names:
        return jsonify({"error": "Unknown agent"}), 404

    return jsonify({
        "agent_name": agent_name,
        "persona": persona_store.get(agent_name)
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

    action_text = str(data.get("action", "")).strip()
    location_name = data.get("location", "")

    state, effects = complete_agent_action(
        agent_name,
        location_name=location_name,
        action_text=action_text,
        elapsed_game_minutes=data.get("elapsed_game_minutes", 0),
        day=data.get("day"),
        time=data.get("time"),
        sleeping=bool(data.get("sleeping", False)),
        social_contact=bool(data.get("social_contact", False))
    )

    # 将已完成的动作反馈到滚动记忆库中，以便下一次决策能够基于
    # 实际发生过的事情（不包括日常姿态动作）。
    if action_text and action_text not in {"wake up", "sleep", "rest"}:
        agent = agents_by_name[agent_name]
        with state_lock:
            try:
                life_day = max(1, int(data.get("day") or simulation_progress.get("current_life_day", 1)))
            except (TypeError, ValueError):
                life_day = simulation_progress.get("current_life_day", 1)
            agent.record_completed_action(action_text, location_name, life_day=life_day)

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

