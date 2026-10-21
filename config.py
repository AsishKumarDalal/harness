import json
import os
import shutil
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load .env sitting next to this file, regardless of where you run from
ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")


def _get(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


# ---------------------------------------------------------------------------
# Two places, never mixed up:
#   HARNESS_HOME — where the HARNESS keeps its own files (state, rules, exports)
#   START_DIR    — the PROJECT the agent works in (read/write target)
# The harness never drops a single file of its own into START_DIR.
# ---------------------------------------------------------------------------
HARNESS_HOME = Path(_get("HARNESS_HOME") or (Path.home() / ".harness")).expanduser()
LEGACY_STATE_DIR = ROOT / ".harness"      # v1 kept state inside the project


def _project_dir() -> Path:
    """Which project folder this run works on.

    Order: --project <dir>  ->  PROJECT_DIR env  ->  a bare path argument  ->  cwd.
    """
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a in ("-p", "--project") and i + 1 < len(args):
            return Path(args[i + 1]).expanduser().resolve()
        if a.startswith("--project="):
            return Path(a.split("=", 1)[1]).expanduser().resolve()
    env = _get("PROJECT_DIR")
    if env:
        return Path(env).expanduser().resolve()
    for a in args:
        if a.startswith("-"):
            continue
        p = Path(a).expanduser()
        if p.is_dir() or "/" in a or a.startswith("~"):   # looks like a folder
            return p.resolve()
    return Path.cwd().resolve()


def set_project_dir(path) -> Path:
    """Point the agent at a different project folder (runtime switch)."""
    global START_DIR
    START_DIR = Path(path).expanduser().resolve()
    return START_DIR


# ---------------------------------------------------------------------------
# Machine-wide settings (survive every run, live in HARNESS_HOME)
# ---------------------------------------------------------------------------

SETTINGS_PATH = HARNESS_HOME / "settings.json"


def _load_settings() -> dict:
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    return data if isinstance(data, dict) else {}


SETTINGS = _load_settings()


def save_settings() -> None:
    """Write the machine-wide settings back to disk."""
    try:
        HARNESS_HOME.mkdir(parents=True, exist_ok=True)
        SETTINGS_PATH.write_text(json.dumps(SETTINGS, indent=2), encoding="utf-8")
    except OSError as exc:
        print(f"could not save {SETTINGS_PATH}: {exc}")


def get_model() -> str:
    """The model to use: the machine-wide choice, else MODEL from .env."""
    chosen = str(SETTINGS.get("model") or "").strip()
    return chosen or _get("MODEL", "gpt-4o-mini")


def set_model(name: str) -> str:
    """Set the model for THIS MACHINE (every project, every run).

    The choice is kept in $HARNESS_HOME/settings.json, so it follows you
    from project to project.
    """
    global MODEL
    name = (name or "").strip()
    if not name:
        return "model must not be empty"
    SETTINGS["model"] = name
    save_settings()
    MODEL = name
    return f"model set to {name} (saved for this machine: {SETTINGS_PATH})"


def model_source() -> str:
    """Where the current model comes from: 'saved', '.env' or 'default'."""
    if str(SETTINGS.get("model") or "").strip():
        return "saved"
    return ".env" if _get("MODEL") else "default"


def migrate_legacy_state() -> None:
    """v1 stored state in <harness>/.harness — move it to HARNESS_HOME, once."""
    legacy = LEGACY_STATE_DIR
    if not legacy.is_dir():
        return
    try:
        HARNESS_HOME.mkdir(parents=True, exist_ok=True)
        exports = HARNESS_HOME / "exports"
        for item in legacy.iterdir():
            dest = (exports / item.name if item.suffix == ".jsonl"
                    else HARNESS_HOME / item.name)
            if dest.exists():
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(item), str(dest))
        legacy.rmdir()
    except OSError:
        pass


MAX_SUBAGENTS        = int(_get("MAX_SUBAGENTS", "3"))    # parallel children (Hermes: 10; ours lower: one model server)
SUBAGENT_MAX_TURNS   = int(_get("SUBAGENT_MAX_TURNS", "12"))
SUBAGENT_SUMMARY_CHARS = int(_get("SUBAGENT_SUMMARY_CHARS", "8000"))  # per-child cap on what the parent sees
MAX_SPAWN_DEPTH      = int(_get("MAX_SPAWN_DEPTH", "1"))  # 1 = flat: children cannot delegate (Hermes default)
API_KEY  = _get("OPENAI_API_KEY")
BASE_URL = _get("BASE_URL") or None   # None = official OpenAI endpoint
MODEL    = get_model()                 # the machine-wide choice, else MODEL from .env
START_DIR  = _project_dir()      # the PROJECT the agent works in (not the harness home)


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
            f"  2. Paste it into {ROOT / '.env'}\n"
            "  3. Run: harness"
        )
    return API_KEY


migrate_legacy_state()      # v1 in-project state -> HARNESS_HOME (one-time)
