import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env sitting next to this file, regardless of where you run from
ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")


def _get(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()

MAX_SUBAGENTS        = int(_get("MAX_SUBAGENTS", "3"))    # parallel children (Hermes: 10; ours lower: one model server)
SUBAGENT_MAX_TURNS   = int(_get("SUBAGENT_MAX_TURNS", "12"))
SUBAGENT_SUMMARY_CHARS = int(_get("SUBAGENT_SUMMARY_CHARS", "8000"))  # per-child cap on what the parent sees
MAX_SPAWN_DEPTH      = int(_get("MAX_SPAWN_DEPTH", "1"))  # 1 = flat: children cannot delegate (Hermes default)
API_KEY  = _get("OPENAI_API_KEY")
BASE_URL = _get("BASE_URL") or None   # None = official OpenAI endpoint
MODEL    = _get("MODEL", "gpt-4o-mini")
START_DIR  = ROOT  


CONTEXT_LIMIT   = int(_get("CONTEXT_LIMIT", "50000"))    # your model's window
CONTEXT_RESERVE = int(_get("CONTEXT_RESERVE", "12000"))  # output room + next tool blob
CONTEXT_BUDGET  = CONTEXT_LIMIT - CONTEXT_RESERVE        # what the conversation may use
PRUNE_AT        = 0.45      # tier 1: stub old tool outputs (free, no LLM)
COMPACT_AT      = 0.75      # tier 2: LLM summarizes the middle (Hermes default 0.75)
COMPACT_TO      = 0.60      # compact DOWN to this (one deep cut beats ten nervous ones)
KEEP_HEAD       = 3         # protected rows after system (Hermes protect_first_n)
KEEP_TAIL       = 6         # protected recent rows (Hermes protect_last_n)
SUMMARY_MODEL   = _get("SUMMARY_MODEL") 


def require_api_key() -> str:
    """Guard so the failure message is friendly, not a stack trace."""
    if not API_KEY or "REPLACE" in API_KEY or "..." in API_KEY:
        raise RuntimeError(
            "OPENAI_API_KEY is not set.\n"
            "  1. Get a key: https://platform.openai.com/api-keys\n"
            "  2. Paste it into the .env file in this folder\n"
            "  3. Run: python main.py"
        )
    return API_KEY