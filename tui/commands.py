"""tui/commands.py — slash commands.

Parsed BEFORE the text reaches the model. Deliberately free of Textual
imports so it can be unit-tested on its own (see test/test_tui_commands.py).
"""

from __future__ import annotations

from dataclasses import dataclass

#: The commands the app understands.
KNOWN_COMMANDS: tuple[str, ...] = ("new", "sessions", "model", "clear", "help")


@dataclass(frozen=True)
class Command:
    """A parsed slash command: its name and the rest of the line."""

    name: str
    arg: str = ""


def parse_command(text: str) -> Command | None:
    """Parse a line that starts with `/`.

    Returns None when the text is not a command (plain chat, empty line, or
    a lone `/`).
    """
    stripped = (text or "").strip()
    if not stripped.startswith("/"):
        return None
    body = stripped[1:]
    if not body:
        return None
    name, _, arg = body.partition(" ")
    name = name.strip().lower()
    if not name:
        return None
    return Command(name=name, arg=arg.strip())


def is_known(command: Command) -> bool:
    """Is this a command the app implements?"""
    return command.name in KNOWN_COMMANDS


def suggestions() -> list[str]:
    """Command names, for the help text."""
    return list(KNOWN_COMMANDS)
