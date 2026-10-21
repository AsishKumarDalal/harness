"""Offline probe for tui/commands.py — no model server, no Textual needed.

Run:  .venv/bin/python test/test_tui_commands.py   (from project root)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tui.commands import (  # noqa: E402
    KNOWN_COMMANDS,
    Command,
    is_known,
    parse_command,
    suggestions,
)

passed = failed = 0


def check(label, got, want):
    global passed, failed
    ok = got == want
    print(("ok  " if ok else "FAIL"), label, "->", got)
    passed += ok
    failed += not ok


# --- plain text is not a command --------------------------------------------
check("plain text", parse_command("hello there"), None)
check("empty", parse_command(""), None)
check("none", parse_command(None), None)
check("lone slash", parse_command("/"), None)
check("slash only spaces", parse_command("   /   "), None)
check("not a slash", parse_command("not /a command"), None)

# --- simple commands --------------------------------------------------------
check("/new", parse_command("/new"), Command("new", ""))
check("/help", parse_command("/help"), Command("help", ""))
check("/clear", parse_command("/clear"), Command("clear", ""))
check("/sessions", parse_command("/sessions"), Command("sessions", ""))
check("/model", parse_command("/model"), Command("model", ""))

# --- with an argument --------------------------------------------------------
check("/new with title", parse_command("/new my project"), Command("new", "my project"))
check("/model with name", parse_command("/model gpt-4o"), Command("model", "gpt-4o"))
check("arg keeps spaces", parse_command("/new  two  words "), Command("new", "two  words"))

# --- whitespace and case -----------------------------------------------------
check("leading space", parse_command("   /help"), Command("help", ""))
check("trailing space", parse_command("/help   "), Command("help", ""))
check("upper case", parse_command("/HELP"), Command("help", ""))
check("mixed case", parse_command("/New Title"), Command("new", "Title"))
check("arg keeps its case", parse_command("/new My Project"), Command("new", "My Project"))

# --- known / unknown ---------------------------------------------------------
check("known /new", is_known(parse_command("/new")), True)
check("known /help", is_known(parse_command("/help")), True)
check("unknown /nope", is_known(parse_command("/nope")), False)
check("unknown keeps arg", parse_command("/nope x"), Command("nope", "x"))

# --- the registry itself -----------------------------------------------------
check("known commands", set(KNOWN_COMMANDS), {"new", "sessions", "model", "skills", "clear", "help"})
check("suggestions match", set(suggestions()), set(KNOWN_COMMANDS))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
