import json
import os
import subprocess
import threading
from pathlib import Path

import safety
import sessions
import config

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
    p = (config.START_DIR / path).resolve()
    p.relative_to(config.START_DIR.resolve())      # raises if outside the project
    return p


def list_files() -> str:
    out = []
    for p in sorted(config.START_DIR.rglob("*")):
        if any(part in SKIP_DIRS or part.startswith(".") for part in p.parts):
            continue
        out.append(str(p.relative_to(config.START_DIR)) + ("/" if p.is_dir() else ""))
    text = "\n".join(out) or "(empty)"
    if len(text) > 4000:
        text = text[:4000] + "\n...[truncated]"
    return text


def read_file(path: str) -> str:
    p = _safe(path)
    if safety.is_secret_path(p):
        return "error: refusing to read a secret file"
    text = p.read_text(encoding="utf-8")
    if safety.looks_secret(text):
        return "error: refusing to read a secret file"
    return text

def write_file(path: str, content: str) -> str:
    p = _safe(path)
    if safety.is_secret_path(p):
        return "error: refusing to write a protected/secret file"
    p.parent.mkdir(parents=True, exist_ok=True)
    existed = p.exists()
    p.write_text(content, encoding="utf-8")
    action = "overwrote" if existed else "created"
    return f"{action} {path} ({len(content)} chars)"


def edit_file(path: str, old_string: str, new_string: str) -> str:
    if not old_string:
        return "error: old_string is empty"
    p = _safe(path)
    if safety.is_secret_path(p):
        return "error: refusing to edit a protected/secret file"
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
    for p in sorted(config.START_DIR.rglob("*")):
        if p.suffix not in SEARCH_EXTS or not p.is_file():
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if safety.is_secret_path(p):
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if needle in line:
                hits.append(f"{p.relative_to(config.START_DIR)}:{i}: {line.strip()[:80]}")
        if len(hits) >= 50:
            break
    return "\n".join(hits) if hits else f"no matches for '{needle}'"

def run_command(command: str) -> str:
    blocked = safety.command_guard(command)      # hardline + secret + redirect guards
    if blocked:
        return blocked
    r = subprocess.run(
        command, shell=True, cwd=config.START_DIR,   # pinned: commands run in the project folder
        capture_output=True, text=True, timeout=60,
        env=safety.safe_env(),                  # no API keys / tokens in the child
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


def web_search(query: str, max_results: int = 5) -> str:
    """Search the web (DuckDuckGo, no API key)."""
    import web
    return web.search(query, max_results=max_results)


def web_fetch(url: str) -> str:
    """Fetch a URL and return the page as text (HTML stripped)."""
    import web
    return web.fetch(url)


def skill(name: str) -> str:
    """Load a skill's instructions (the list is in your system prompt)."""
    import skills
    return skills.load_skill(name)


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
    "web_search":    web_search,
    "web_fetch":     web_fetch,
    "skill":         skill,
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
    _tool("web_search",
          "Search the web (DuckDuckGo, no API key). Returns the top results with "
          "title, url and a short snippet. Use it to look up documentation, "
          "libraries, error messages or anything that is not in the project.",
          {"query": _str("what to search for"),
           "max_results": {"type": "integer",
                           "description": "how many results (default 5, max 20)"}},
          ["query"]),
    _tool("web_fetch",
          "Fetch a URL and return the page as plain text (HTML is stripped, "
          "github.com/.../blob/... URLs are turned into the raw file). Use it to "
          "read documentation, a GitHub source file, or an API answer.",
          {"url": _str("the full http(s) URL to fetch")},
          ["url"]),
    _tool("skill",
          "Load the full instructions of a skill. The available skills are "
          "listed in your system prompt; load one when the task fits it.",
          {"name": _str("the skill name, e.g. 'pdf'")},
          ["name"]),
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
    blocked = safety.blocked_tool_message(name, args)
    if blocked:
        return blocked
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