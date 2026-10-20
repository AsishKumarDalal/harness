import json
import os
import subprocess
import threading
from pathlib import Path

import sessions
from config import START_DIR

SKIP_DIRS = {".venv", "__pycache__", ".git"}
SEARCH_EXTS = {".py", ".md", ".txt", ".json", ".toml", ".yaml", ".yml",
               ".cfg", ".ini", ".sh", ".env.example"}

_allowed = threading.local()      # per-thread tool restriction (children)
_quiet = threading.local()        # per-thread "print nothing" flag (children)

def allow_tools(names=None):
    """Restrict callable tools for THIS thread only. None = no restriction."""
    _allowed.names = None if names is None else set(names)

def set_quiet(q=True):
    """Silence tool printing for THIS thread only (parallel children each
    silence themselves; the parent's thread stays verbose no matter what)."""
    _quiet.v = q

def run_tool_print_allowed():
    return not getattr(_quiet, "v", False)

def _safe(path: str) -> Path:
    """resolve() the path; reject anything escaping the project folder."""
    p = (START_DIR / path).resolve()
    if not str(p).startswith(str(START_DIR)):
        raise ValueError(f"outside project: {path}")
    return p


def list_files() -> str:
    out = []
    for p in sorted(START_DIR.rglob("*")):
        if any(part in SKIP_DIRS or part.startswith(".") for part in p.parts):
            continue
        out.append(str(p.relative_to(START_DIR)) + ("/" if p.is_dir() else ""))
    text = "\n".join(out) or "(empty)"
    if len(text) > 4000:
        text = text[:4000] + "\n...[truncated]"
    return text


BLOCKED_FILES = {".env"}

def read_file(path: str) -> str:
    p = _safe(path)
    if p.name in BLOCKED_FILES or p.suffix in (".key", ".pem"):
        return "error: refusing to read a secret file"
    text = p.read_text(encoding="utf-8")
    return text

def write_file(path: str, content: str) -> str:
    p = _safe(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    existed = p.exists()
    p.write_text(content, encoding="utf-8")
    action = "overwrote" if existed else "created"
    return f"{action} {path} ({len(content)} chars)"


def edit_file(path: str, old_string: str, new_string: str) -> str:
    if not old_string:
        return "error: old_string is empty"
    p = _safe(path)
    text = p.read_text(encoding="utf-8")
    count = text.count(old_string)
    if count != 1:
        return (f"error: old_string appears {count} times in {path} "
                f"(need exactly 1 — add more context around it)")
    p.write_text(text.replace(old_string, new_string), encoding="utf-8")
    return f"edit accepted: replaced {len(old_string)} chars -> {len(new_string)} chars in {path}"


def search_files(needle: str) -> str:
    if not needle:
        return "error: needle is empty"
    hits = []
    for p in sorted(START_DIR.rglob("*")):
        if p.suffix not in SEARCH_EXTS or not p.is_file():
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if needle in line:
                hits.append(f"{p.relative_to(START_DIR)}:{i}: {line.strip()[:80]}")
        if len(hits) >= 50:
            break
    return "\n".join(hits) if hits else f"no matches for '{needle}'"

def run_command(command: str) -> str:
    r = subprocess.run(
        command, shell=True, cwd=START_DIR,     # pinned: commands run in the project folder
        capture_output=True, text=True, timeout=60,
    )
    out = r.stdout.strip()
    if r.stderr.strip():
        out += "\n[stderr] " + r.stderr.strip()
    out += f"\n[exit={r.returncode}]"
    if len(out) > 4000:
        out = out[:4000] + "\n...[truncated]"
    return out or "(no output)"

def session_search(query: str, limit: int = 5) -> str:
    """Search the notebook: past sessions + archived/pruned tool output."""
    hits = sessions.search(query, limit=limit)
    if not hits:
        return f"no matches for '{query}'"
    out = []
    for h in hits:
        text = (h.get("content") or "").replace("\n", " ")[:300]
        out.append(f"[{h['session_id']} {h['role']}] {text}")
    return "\n".join(out)


def delegate(tasks=None) -> str:
    """Spawn subagents in parallel; they get ONLY goal+context; one summary each."""
    import subagents
    return subagents.run_batch(tasks)


REGISTRY = {
    "list_files":    list_files,
    "read_file":     read_file,
    "write_file":    write_file,
    "edit_file":     edit_file,
    "search_files":  search_files,
    "run_command":   run_command,
    "session_search": session_search,
    "delegate":      delegate,
}
 
 
def _tool(name: str, description: str, params=None, required=None):
    if params is None:
        params = {}
    if required is None:
        required = []
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": params,
                "required": required,
            },
        },
    }
def _str( desc: str = ""):
    return {"type": "string", "description": desc}


SCHEMA = [
    _tool("list_files", "List all files in the project."),
    _tool("read_file", "Read a file's contents.",
          {"path": _str("file path, e.g. main.py")}, ["path"]),
    _tool("write_file", "Create or fully overwrite a file.",
          {"path": _str("file path"), "content": _str("full file content")},
          ["path", "content"]),
    _tool("edit_file", "Search-and-replace exact text inside a file.",
          {"path": _str("file path"),
           "old_string": _str("exact text to replace (must be unique)"),
           "new_string": _str("replacement text")},
          ["path", "old_string", "new_string"]),
    _tool("search_files", "Grep-like search across project files.",
          {"needle": _str("text to find")}, ["needle"]),
    _tool("run_command", "Run a shell command in the project folder.",
          {"command": _str("e.g. 'python -m py_compile main.py'")}, ["command"]),
    _tool("session_search", "Search past sessions and archived/pruned tool output.",
          {"query": _str("text to search for"),
           "limit": {"type": "integer", "description": "max results (default 5)"}},
          ["query"]),
    _tool("delegate",
          "Spawn parallel subagents. Each child sees ONLY its goal+context (it knows "
          "nothing about our conversation) and returns a short final summary. Use for "
          "independent, parallelizable work: research + report, batch code review per "
          "file, multi-file refactors that don't depend on each other. Do NOT use for "
          "quick single-step tasks. All tasks of one call run AT THE SAME TIME; if you "
          "issue SEVERAL delegate calls in one turn, those batches also run at the same "
          "time. Prefer ONE call with a tasks list when the subtasks are siblings.",
          {"tasks": {
              "type": "array",
              "minItems": 1,
              "description": "one object per subagent",
              "items": {
                  "type": "object",
                  "properties": {
                      "goal": _str("what THIS child must accomplish. Be specific and "
                                   "self-contained — it sees nothing from our conversation."),
                      "context": _str("background the child needs: file paths, error text, "
                                      "constraints. Repeat it in every task that needs it."),
                  },
                  "required": ["goal"],
              },
          }},
          ["tasks"]),
]

def run_tool(call) -> str:
    name = call.function.name
    allowed = getattr(_allowed, "names", None)
    if allowed is not None and name not in allowed:
        return f"Error: tool '{name}' is not available to this agent"
    args = json.loads(call.function.arguments or "{}")   # arguments = JSON string
    try:
        result = REGISTRY[name](**args)
    except Exception as e:
        result = f"Error: {e}"      # errors go back so the model can recover
    result = str(result) or "(no output)"
    if len(result) > 5000:          # safety net: never blow the context window
        result = result[:5000] + "\n...[truncated]"
    if run_tool_print_allowed():    # children run silent (thread-local)
        print(f"   {name} {args}")  # you can SEE the agent working
    return result