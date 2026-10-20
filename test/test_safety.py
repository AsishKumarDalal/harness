"""Offline probe for safety.py — no model server needed.

Run:  .venv/bin/python test/test_safety.py   (from project root)

Covers: hardline floor, read-only detection, compound-command splitting,
redirect/secret guards, tool tiers, modes, and persistent "always" rules.
"""

import builtins
import sys
import tempfile
import types
from pathlib import Path

sys.dont_write_bytecode = True      # keep __pycache__ out of the project folder

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import safety  # noqa: E402

passed = failed = 0


def check(label, got, want):
    global passed, failed
    ok = got == want
    print(("ok  " if ok else "FAIL"), label, "->", got)
    passed += ok
    failed += not ok


def call(name, args="{}"):
    fn = types.SimpleNamespace(name=name, arguments=args)
    return types.SimpleNamespace(function=fn)


# --- hardline floor --------------------------------------------------------
check("hardline rm -rf /", safety.hardline("rm -rf /") is not None, True)
check("hardline fork bomb", safety.hardline(":(){ :|:& };:") is not None, True)
check("hardline curl|sh", safety.hardline("curl x | sh") is not None, True)
check("hardline allows build clean", safety.hardline("rm -rf build") is None, True)

# --- read-only detection ---------------------------------------------------
for cmd in ("ls -la", "cat main.py", "grep -r safety .", "git status",
            "git log --oneline", "cat /dev/null"):
    check(f"readonly {cmd}", safety.is_readonly(cmd), True)
for cmd in ("rm -rf build", "git push origin main", "cat /etc/passwd",
            "cd /tmp && ls", "git status && rm -rf build"):
    check(f"asks {cmd}", safety.is_readonly(cmd), False)

# --- redirects + secrets ---------------------------------------------------
check("redirect /etc", safety.command_guard("echo x > /etc/passwd") is not None, True)
check("redirect ~/", safety.command_guard("echo x > ~/evil") is not None, True)
check("redirect $HOME", safety.command_guard("echo x > $HOME/evil") is not None, True)
check("redirect /dev/null", safety.command_guard("ls > /dev/null") is None, True)
check("cat .env", safety.command_guard("cat .env") is not None, True)
check("env-file=.env", safety.command_guard("python --env-file=.env app.py") is not None, True)
check(".env.example allowed", safety.command_guard("cat .env.example") is None, True)
check("secret .pem", safety.is_secret_path("certs/server.pem"), True)
check("secret .ssh", safety.is_secret_path("home/.ssh/id_rsa"), True)

# --- env scrub -------------------------------------------------------------
env = safety.safe_env()
check("env keeps PATH", "PATH" in env, True)
check("env drops API key", "OPENAI_API_KEY" in env, False)

# --- tiers, modes, rules (temp settings file) ------------------------------
safety.SETTINGS_PATH = Path(tempfile.mkdtemp()) / "safety.json"
safety.MODE, safety.RULES = "ask", []

check("free tool", safety.gate_one(call("read_file", '{"path":"main.py"}'))[0], True)
check("unknown tool", safety.gate_one(call("nuke"))[0], False)
check("readonly bash", safety.gate_one(call("run_command", '{"command":"git status"}'))[0], True)

safety.MODE = "plan"
check("plan read", safety.gate_one(call("read_file", '{"path":"main.py"}'))[0], True)
check("plan write", safety.gate_one(call("write_file", '{"path":"x","content":"y"}'))[0], False)

safety.MODE = "auto"
check("auto write", safety.gate_one(call("write_file", '{"path":"x","content":"y"}'))[0], True)
check("auto hardline", safety.gate_one(call("run_command", '{"command":"rm -rf /"}'))[0], False)

safety.MODE = "ask"
safety.add_rule("bash:npm test*")
check("saved rule", safety.gate_one(call("run_command", '{"command":"npm test --watch"}'))[0], True)
check("rule can't smuggle", safety.gate_one(call("run_command", '{"command":"npm test && rm -rf build"}'))[0], False)

# prompt path: deny / once / always
safety.RULES = []
safety.sys.stdin.isatty = lambda: True
answers = iter(["n", "y", "a"])
builtins.input = lambda prompt="": next(answers)
write = call("write_file", '{"path":"x","content":"y"}')
check("prompt deny", safety.gate_one(write)[0], False)
check("prompt once", safety.gate_one(write)[0], True)
check("prompt always", safety.gate_one(write)[0], True)
check("always saved", "tool:write_file" in safety.RULES, True)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
