import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).with_name(".env"))
except ImportError:
    pass

# OpenAI-compatible LLM endpoint configuration (DeepSeek by default).
# Legacy ANTHROPIC_/CLAUDE_ variable names are still honoured as fallbacks.
LLM_API_KEY = (
    os.getenv("LLM_API_KEY")
    or os.getenv("DEEPSEEK_API_KEY")
    or os.getenv("ANTHROPIC_API_KEY")
    or os.getenv("CLAUDE_API_KEY", "")
)
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat")

# Observability: structured JSONL trace of every LLM call.
LLM_TRACE_ENABLED = os.getenv("LLM_TRACE_ENABLED", "true").lower() not in ("0", "false", "no")
LLM_TRACE_FILE = os.getenv("LLM_TRACE_FILE", str(Path(__file__).with_name("logs") / "llm_trace.jsonl"))
LLM_TRACE_MAX_CHARS = int(os.getenv("LLM_TRACE_MAX_CHARS", "2000"))

# Memory retrieval: Stanford-style three-factor scoring
# (recency x importance x relevance). Relevance uses local embeddings via
# fastembed; if the model is unavailable, retrieval degrades to recency order.
RETRIEVAL_ENABLED = os.getenv("RETRIEVAL_ENABLED", "true").lower() not in ("0", "false", "no")
EMBED_MODEL = os.getenv("EMBED_MODEL", "BAAI/bge-small-en-v1.5")
RETRIEVAL_RECENCY_DECAY = float(os.getenv("RETRIEVAL_RECENCY_DECAY", "0.9"))
RETRIEVAL_W_RECENCY = float(os.getenv("RETRIEVAL_W_RECENCY", "1.0"))
RETRIEVAL_W_IMPORTANCE = float(os.getenv("RETRIEVAL_W_IMPORTANCE", "1.0"))
RETRIEVAL_W_RELEVANCE = float(os.getenv("RETRIEVAL_W_RELEVANCE", "1.0"))
