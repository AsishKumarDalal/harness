"""tui/events.py — the small events the adapter hands to the UI.

The harness core prints to stdout; the TUI needs structure instead. These
dataclasses are that structure: the adapter turns harness activity into them
and the widgets render them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Token:
    """A piece of the assistant's answer text."""

    text: str


@dataclass
class Thinking:
    """A piece of the model's reasoning (dimmed in the UI)."""

    text: str


@dataclass
class ToolCall:
    """The model asked for a tool to run."""

    call_id: str
    name: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResult:
    """A tool finished (or was refused)."""

    call_id: str
    name: str
    output: str = ""
    status: str = "done"          # done | failed | denied


@dataclass
class ToolDiff:
    """Before/after of a file the agent changed."""

    call_id: str
    path: str
    diff: str


@dataclass
class ApprovalNeeded:
    """The agent wants to run something that needs a human yes."""

    call_id: str
    name: str
    args: dict[str, Any] = field(default_factory=dict)
    summary: str = ""


@dataclass
class TurnDone:
    """The model answered with no further tool calls."""

    content: str = ""


@dataclass
class TurnError:
    """Something went wrong during the turn."""

    message: str


@dataclass
class TurnEnd:
    """The turn is over (always the last event of a turn)."""

    cancelled: bool = False
