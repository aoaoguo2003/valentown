import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).with_name(".env"))
except ImportError:
    pass

# 兼容 OpenAI 的 LLM 接口配置（默认使用 DeepSeek）。
# 仍会兼容旧的 ANTHROPIC_/CLAUDE_ 环境变量名作为备用。
LLM_API_KEY = (
    os.getenv("LLM_API_KEY")
    or os.getenv("DEEPSEEK_API_KEY")
    or os.getenv("ANTHROPIC_API_KEY")
    or os.getenv("CLAUDE_API_KEY", "")
)
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat")

# 可观测性：为每次 LLM 调用记录结构化的 JSONL 追踪日志。
LLM_TRACE_ENABLED = os.getenv("LLM_TRACE_ENABLED", "true").lower() not in ("0", "false", "no")
LLM_TRACE_FILE = os.getenv("LLM_TRACE_FILE", str(Path(__file__).with_name("logs") / "llm_trace.jsonl"))
LLM_TRACE_MAX_CHARS = int(os.getenv("LLM_TRACE_MAX_CHARS", "2000"))

# 记忆检索：采用斯坦福式的三因子评分
#（近因性 x 重要性 x 相关性）。相关性通过 fastembed 的本地嵌入模型计算；
# 若模型不可用，则检索会退化为按近因排序。
RETRIEVAL_ENABLED = os.getenv("RETRIEVAL_ENABLED", "true").lower() not in ("0", "false", "no")
EMBED_MODEL = os.getenv("EMBED_MODEL", "BAAI/bge-small-en-v1.5")
RETRIEVAL_RECENCY_DECAY = float(os.getenv("RETRIEVAL_RECENCY_DECAY", "0.9"))
RETRIEVAL_W_RECENCY = float(os.getenv("RETRIEVAL_W_RECENCY", "1.0"))
RETRIEVAL_W_IMPORTANCE = float(os.getenv("RETRIEVAL_W_IMPORTANCE", "1.0"))
RETRIEVAL_W_RELEVANCE = float(os.getenv("RETRIEVAL_W_RELEVANCE", "1.0"))
