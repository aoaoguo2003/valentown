import os
from pathlib import Path

# 所有运行期存档的根目录。
#
# 写在这里，而不是让各个模块自己 `Path(__file__).with_name(...)`——
# 因为**模块会搬家，config.py 不会**。分包那次，economy / goals /
# mailbox / agent_state 四份存档跟着各自的模块挪进了子包，240 个测试
# 全绿（测试都用 tmp_path），是 git status 里冒出来一个
# backend/world/economy.json 才暴露的。
DATA_DIR = Path(__file__).resolve().parent

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).with_name(".env"))
except ImportError:
    pass

# DeepSeek 的 OpenAI 兼容接口配置。
LLM_API_KEY = os.getenv("LLM_API_KEY") or os.getenv("DEEPSEEK_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
# 旧别名 deepseek-chat / deepseek-reasoner 已于 2026-07-24 停止解析，
# 二者原本分别对应 v4-flash 的非思考模式与思考模式。
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-v4-flash")

# 可观测性：为每次 LLM 调用记录结构化的 JSONL 追踪日志。
LLM_TRACE_ENABLED = os.getenv("LLM_TRACE_ENABLED", "true").lower() not in ("0", "false", "no")
LLM_TRACE_FILE = os.getenv("LLM_TRACE_FILE", str(Path(__file__).with_name("logs") / "llm_trace.jsonl"))
LLM_TRACE_MAX_CHARS = int(os.getenv("LLM_TRACE_MAX_CHARS", "2000"))

# 动作执行事件（接受/拒绝及理由）单独存一个 JSONL，避免破坏
# scripts/llm_stats.py 对 LLM 追踪日志结构的假设。
ACTION_TRACE_FILE = os.getenv(
    "ACTION_TRACE_FILE", str(Path(__file__).with_name("logs") / "action_trace.jsonl"))

# 记忆检索：采用斯坦福式的三因子评分
#（近因性 x 重要性 x 相关性）。相关性通过 fastembed 的本地嵌入模型计算；
# 若模型不可用，则检索会退化为按近因排序。
RETRIEVAL_ENABLED = os.getenv("RETRIEVAL_ENABLED", "true").lower() not in ("0", "false", "no")
EMBED_MODEL = os.getenv("EMBED_MODEL", "BAAI/bge-small-en-v1.5")
RETRIEVAL_RECENCY_DECAY = float(os.getenv("RETRIEVAL_RECENCY_DECAY", "0.9"))
RETRIEVAL_W_RECENCY = float(os.getenv("RETRIEVAL_W_RECENCY", "1.0"))
RETRIEVAL_W_IMPORTANCE = float(os.getenv("RETRIEVAL_W_IMPORTANCE", "1.0"))
RETRIEVAL_W_RELEVANCE = float(os.getenv("RETRIEVAL_W_RELEVANCE", "1.0"))

# 天气：这个项目里唯一的真实外部依赖（Open-Meteo，免费且无需 API key）。
# 选伦敦不是因为它特别，是因为它多雨——天气必须真的会变，否则"下雨改计划"
# 那条分支永远走不到，这个系统对决策就毫无影响。
WEATHER_ENABLED = os.getenv("WEATHER_ENABLED", "true").lower() not in ("0", "false", "no")
WEATHER_LATITUDE = os.getenv("WEATHER_LATITUDE", "51.5074")      # London
WEATHER_LONGITUDE = os.getenv("WEATHER_LONGITUDE", "-0.1278")
WEATHER_TIMEZONE = os.getenv("WEATHER_TIMEZONE", "Europe%2FLondon")
WEATHER_TIMEOUT_SECONDS = float(os.getenv("WEATHER_TIMEOUT_SECONDS", "8"))
