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
