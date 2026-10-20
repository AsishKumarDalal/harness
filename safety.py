"""safety.py — the permission gate (simple, but full-featured).

Design borrowed from Claude Code + Hermes:
  1. hardline blocklist   — never allowed, no prompt, no override
  2. read-only commands   — run free (ls, cat, grep, git status ...)
  3. tiered tools         — reads free, writes/exec/delegate need approval
  4. persistent rules     — "always" answers saved to <HARNESS_HOME>/safety.json
  5. modes                — ask (default) | auto | plan
  6. guards               — env scrub, redirect targets, secret paths

Rule syntax in safety.json:
  "bash:<glob>"   e.g. "bash:npm test*"
  "tool:<name>"   e.g. "tool:write_file"

The OS is still the real security boundary; this stops accidents and
careless commands, not a determined attacker.
"""

import fnmatch
import json
import os
import re
import shlex
import sys
from pathlib import Path

import config

SETTINGS_PATH = config.HARNESS_HOME / "safety.json"   # lives OUTSIDE the project
MODES = ("ask", "auto", "plan")

FREE_TOOLS = {"list_files", "read_file", "search_files", "session_search", "web_search"}
ASK_TOOLS = {"write_file", "edit_file", "run_command", "delegate", "web_fetch"}
ALL_TOOLS = FREE_TOOLS | ASK_TOOLS

# ---------------------------------------------------------------------------
# settings (persisted)
# ---------------------------------------------------------------------------

def _load():
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    mode = data.get("mode", "ask")
    rules = [r for r in data.get("allow", []) if isinstance(r, str)]
    return (mode if mode in MODES else "ask"), rules


MODE, RULES = _load()


def _save():
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(
        json.dumps({"mode": MODE, "allow": sorted(set(RULES))}, indent=2),
        encoding="utf-8",
    )


def mode():
    return MODE


def set_mode(value):
    global MODE
    value = (value or "").strip().lower()
    if value not in MODES:
        return f"mode must be one of: {', '.join(MODES)}"
    MODE = value
    _save()
    return f"safety mode: {MODE}"


def add_rule(rule):
    global RULES
    rule = rule.strip()
    if not rule:
        return "usage: /allow bash:<glob>  or  /allow tool:<name>"
    if not (rule.startswith("bash:") or rule.startswith("tool:")):
        rule = "bash:" + rule
    if rule not in RULES:
        RULES.append(rule)
        _save()
    return f"allowed: {rule}"


def remove_rule(rule):
    global RULES
    rule = rule.strip()
    if rule in RULES:
        RULES.remove(rule)
        _save()
        return f"removed: {rule}"
    return f"not found: {rule}"


def list_rules():
    return sorted(set(RULES))


def describe():
    lines = [f"mode: {MODE}  (ask | auto | plan)",
             "hardline blocklist: always on",
             f"allow rules: {len(RULES)}"]
    lines += [f"  {r}" for r in list_rules()]
    lines.append("free tools: " + ", ".join(sorted(FREE_TOOLS)))
    lines.append("ask tools:  " + ", ".join(sorted(ASK_TOOLS)))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 1. hardline blocklist — always refused
# ---------------------------------------------------------------------------

_HARDLINE = [
    (r"\brm\s+-[a-z]*r[a-z]*f[a-z]*\s+/(?:\s|$|\*)", "recursive delete of /"),
    (r"\brm\s+-[a-z]*f[a-z]*r[a-z]*\s+/(?:\s|$|\*)", "recursive delete of /"),
    (r"--no-preserve-root", "rm --no-preserve-root"),
    (r"\brm\s+-[a-z]*r[a-z]*f[a-z]*\s+(~|\$HOME)(?:\s|$)", "recursive delete of home"),
    (r":\(\)\s*\{.*\};\s*:", "fork bomb"),
    (r"\bdd\b[^\n]*\bof=/dev/(sd|hd|nvme|vd)", "raw disk write"),
    (r"\bmkfs(\.\w+)?\b", "format a filesystem"),
    (r"\b(curl|wget)\b[^|]*\|\s*(sudo\s+)?(ba|z|k)?sh\b", "pipe download to shell"),
    (r"\bchmod\s+-R\s+(777|666)\s+/", "recursive world-writable /"),
    (r"\b(shutdown|reboot|poweroff|halt)\b", "shut down the machine"),
]
_HARDLINE_RE = [(re.compile(p, re.I), why) for p, why in _HARDLINE]


def hardline(command: str):
    flat = " ".join(command.split())
    for rx, why in _HARDLINE_RE:
        if rx.search(flat):
            return f"BLOCKED (hardline): {why}. This command can never run."
    return None


# ---------------------------------------------------------------------------
# 2. read-only command recognition
# ---------------------------------------------------------------------------

READONLY = {
    "ls", "cat", "pwd", "head", "tail", "grep", "wc", "diff", "stat", "du",
    "echo", "which", "file", "tree", "find", "git", "sed", "sort", "uniq",
    "cut", "tr", "nl", "basename", "dirname", "realpath", "readlink", "cd",
    "sha256sum", "md5sum", "true", "false",
}
GIT_SAFE = {
    "status", "log", "diff", "show", "branch", "rev-parse", "remote", "tag",
    "describe", "blame", "ls-files", "grep", "shortlog", "whatchanged",
}
FIND_BAD = {"-delete", "-exec", "-execdir", "-ok", "-okdir",
            "-fprint", "-fprint0", "-files0-from"}
WRAPPERS = {"timeout", "time", "nice", "nohup", "stdbuf", "command",
            "builtin", "xargs", "env"}
SAFE_ASSIGN = {"NODE_ENV", "LANG", "LC_ALL", "TZ", "NO_COLOR", "TERM",
               "PYTHONUNBUFFERED", "CI"}

_PART_SPLIT = re.compile(r"&&|\|\||[;|&]")
_ASSIGN = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=")
_NUM = re.compile(r"^\d+(\.\d+)?[smhd]?$")


def split_compounds(command: str):
    """Split on &&, ||, ;, |, &. Over-splitting is safe: it only asks more."""
    return [p.strip() for p in _PART_SPLIT.split(command) if p.strip()]


def _strip_tokens(tokens):
    """Drop safe env assignments and exec wrappers (timeout, nice, xargs...)."""
    while tokens:
        m = _ASSIGN.match(tokens[0])
        if m:
            if m.group(1) not in SAFE_ASSIGN:
                return None            # unknown env assignment: not safe
            tokens = tokens[1:]
            continue
        head = os.path.basename(tokens[0])
        if head not in WRAPPERS:
            break
        tokens = tokens[1:]
        while tokens and (tokens[0].startswith("-") or _NUM.match(tokens[0])):
            tokens = tokens[1:]
    return tokens


def _read_paths_ok(tokens) -> bool:
    """Read-only shell is still restricted to the project folder."""
    for tok in tokens[1:]:
        if tok.startswith("-"):
            continue
        if tok.startswith("~"):
            return False
        if tok in ("/dev/null", "/dev/stdout", "/dev/stderr"):
            continue
        if tok.startswith("/"):
            if not _path_is_inside(Path(tok)):
                return False
        elif tok.startswith(".."):
            if not _path_is_inside(config.START_DIR / tok):
                return False
    return True


def is_readonly_part(part: str) -> bool:
    if any(x in part for x in ("$(", "`", ">", "<")):
        return False
    try:
        tokens = shlex.split(part)
    except ValueError:
        return False
    tokens = _strip_tokens(tokens)
    if not tokens:
        return False
    cmd = os.path.basename(tokens[0])
    if cmd == "cd":
        if len(tokens) == 1:
            return True
        if len(tokens) != 2 or tokens[1].startswith(("~", "$")) or tokens[1] == "-":
            return False
        p = Path(tokens[1])
        if not p.is_absolute():
            p = config.START_DIR / p
        return _path_is_inside(p)
    if not _read_paths_ok(tokens):
        return False
    if cmd == "git":
        sub = tokens[1] if len(tokens) > 1 else ""
        if sub not in GIT_SAFE:
            return False
        if sub == "branch" and any(
                t.startswith("-") and t not in ("-a", "-r", "-v", "-vv", "--list")
                for t in tokens[2:]):
            return False
        return True
    if cmd == "find":
        return not any(t in FIND_BAD for t in tokens)
    if cmd == "sed":
        return not any(t in ("-i", "--in-place") or t.startswith("--in-place=")
                       for t in tokens)
    if cmd == "sort":
        return not any(t in ("-o", "--output") or t.startswith("--output=")
                       for t in tokens)
    if cmd == "file":
        return not any(t in ("-m", "--magic-file", "-f", "--files-from")
                       for t in tokens)
    return cmd in READONLY


def is_readonly(command: str) -> bool:
    parts = split_compounds(command)
    return bool(parts) and all(is_readonly_part(p) for p in parts)


def _rule_matches(part: str, rule: str) -> bool:
    return (rule.startswith("bash:")
            and fnmatch.fnmatchcase(part.lower(), rule[5:].lower()))


def _command_allowed(command: str) -> bool:
    """Every compound part must be read-only or match a saved rule."""
    parts = split_compounds(command)
    return bool(parts) and all(
        is_readonly_part(p) or any(_rule_matches(p, r) for r in RULES)
        for p in parts
    )


# ---------------------------------------------------------------------------
# 3. secret paths + redirect guard + env scrub
# ---------------------------------------------------------------------------

SECRET_NAMES = {".netrc", "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",
                "credentials", ".npmrc", ".pypirc"}
SECRET_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".jks", ".keystore"}
SECRET_DIRS = {".ssh", ".aws", ".gnupg", ".kube"}
ENV_SAFE = {"PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TERM", "TMPDIR",
            "USER", "LOGNAME", "SHELL", "PWD", "OLDPWD", "TZ", "COLUMNS",
            "LINES", "VIRTUAL_ENV"}
ENV_SECRET_WORDS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD", "AUTH",
                    "CREDENTIAL", "PRIVATE")


def is_secret_name(name: str) -> bool:
    n = name.lower()
    if n in SECRET_NAMES:
        return True
    if n == ".env" or (n.startswith(".env.")
                       and n not in (".env.example", ".env.sample", ".env.template")):
        return True
    return Path(n).suffix in SECRET_SUFFIXES


def is_secret_path(path) -> bool:
    p = Path(path)
    if any(part in SECRET_DIRS for part in p.parts):
        return True
    return is_secret_name(p.name)


def looks_secret(text: str) -> bool:
    return "PRIVATE KEY-----" in text[:4000]


def safe_env():
    """Subprocess env without credentials (PATH stays)."""
    out = {}
    for k, v in os.environ.items():
        if k in ENV_SAFE or not any(w in k.upper() for w in ENV_SECRET_WORDS):
            out[k] = v
    return out


_REDIRECT = re.compile(r"(?:^|[^0-9&])(?:>>?|<)\s*(['\"]?)([^\s;&|'\"]+)\1")
_TEE = re.compile(r"\btee\b(?:\s+-[^\s]+)*\s+([^\s;&|]+)")


def _path_is_inside(path: Path) -> bool:
    try:
        path.resolve().relative_to(config.START_DIR.resolve())
        return True
    except Exception:
        return False


def _check_target(target: str):
    target = target.strip("'\"")
    if not target or target.startswith("&") or target.isdigit():
        return None
    if target in ("/dev/null", "/dev/stdout", "/dev/stderr"):
        return None
    if "$" in target:
        return f"BLOCKED: cannot verify redirect target '{target}'."
    p = Path(target).expanduser()          # ~/x must not pass as a relative path
    if not p.is_absolute():
        p = config.START_DIR / p
    if not _path_is_inside(p):
        return f"BLOCKED: '{target}' is outside the project folder."
    if is_secret_path(p):
        return f"BLOCKED: '{target}' is a protected/secret file."
    return None


def _redirect_guard(command: str):
    for m in _REDIRECT.finditer(command):
        err = _check_target(m.group(2))
        if err:
            return err
    for m in _TEE.finditer(command):
        err = _check_target(m.group(1))
        if err:
            return err
    return None


def _secret_mention_guard(command: str):
    """`cat .env`, `cp .env /tmp`, `--env-file=.env`, ... — cheap protection."""
    for tok in re.split(r"[\s;|&()]+", command):
        tok = tok.strip("'\"")
        if not tok:
            continue
        name = os.path.basename(tok.split("=", 1)[-1]) if "=" in tok else os.path.basename(tok)
        if is_secret_name(name):
            return (f"BLOCKED: '{name}' is a protected/secret file "
                    f"(shell commands may not touch it).")
    return None


def command_guard(command: str):
    """Run before every shell command. Returns an error string or None."""
    return hardline(command) or _secret_mention_guard(command) or _redirect_guard(command)


# ---------------------------------------------------------------------------
# 4. tool tiering + approval prompt
# ---------------------------------------------------------------------------

DENIED_MSG = ("User DENIED this action. Do not retry it; ask the user or "
              "choose a different approach.")


def blocked_tool_message(name: str, args=None):
    """Static policy check used by run_tool (children included)."""
    if name not in ALL_TOOLS:
        return f"Error: tool '{name}' is not permitted by the safety policy."
    if MODE == "plan":
        if name in FREE_TOOLS:
            return None
        if name == "run_command" and args is not None:
            command = str(args.get("command", ""))
            err = command_guard(command)
            if err:
                return err
            if is_readonly(command):
                return None          # read-only shell is fine in plan mode
        return (f"Error: plan mode is on — '{name}' is not read-only. "
                f"Use /mode ask to enable writes and commands.")
    return None


def _remember(name, args):
    global RULES
    if name == "run_command":
        new = [f"bash:{p}" for p in split_compounds(str(args.get("command", "")))
               if not is_readonly_part(p)]
    else:
        new = [f"tool:{name}"]
    for rule in new[:5]:
        if rule and rule not in RULES:
            RULES.append(rule)
    _save()


def _show(name, args):
    print(f"\n  ⚠ approval needed: {name}")
    if name == "run_command":
        print(f"    command: {str(args.get('command', ''))[:500]}")
    elif name in ("write_file", "edit_file"):
        print(f"    path: {args.get('path', '')}")
        if name == "write_file":
            print(f"    content: {len(str(args.get('content', '')))} chars")
        else:
            print(f"    replace {len(str(args.get('old_string', '')))} chars "
                  f"-> {len(str(args.get('new_string', '')))} chars")
    elif name == "delegate":
        for t in (args.get("tasks") or [])[:5]:
            print(f"    task: {str(t.get('goal', ''))[:100]}")
    elif name == "web_fetch":
        print(f"    url: {str(args.get('url', ''))[:500]}")


def gate_one(call):
    """Called from the MAIN thread, before dispatch. Returns (ok, message)."""
    name = call.function.name
    try:
        args = json.loads(call.function.arguments or "{}")
    except Exception:
        return False, "Error: malformed tool arguments."

    static = blocked_tool_message(name, args)
    if static:
        return False, static
    if name in FREE_TOOLS:
        return True, ""

    if name == "run_command":
        command = str(args.get("command", ""))
        err = command_guard(command)
        if err:
            return False, err
        if is_readonly(command) or _command_allowed(command):
            return True, ""
    elif f"tool:{name}" in RULES:
        return True, ""

    if MODE == "auto":
        return True, ""

    if not sys.stdin.isatty():
        return False, ("BLOCKED: approval needed but no interactive terminal. "
                       "Run in ask mode interactively or pre-allow with /allow.")

    _show(name, args)
    try:
        ans = input("    run? [y] once / [a] always / [n] no (default no): ")
    except (EOFError, KeyboardInterrupt):
        ans = "n"
    ans = ans.strip().lower()

    if ans in ("y", "yes"):
        return True, ""
    if ans in ("a", "always"):
        _remember(name, args)
        return True, ""
    return False, DENIED_MSG
