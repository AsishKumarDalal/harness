"""tui/widgets/approval.py — the inline approve/deny prompt."""

from __future__ import annotations

from rich.text import Text
from textual.binding import Binding
from textual.containers import Container
from textual.message import Message
from textual.widgets import Static


class ApprovalPrompt(Container):
    """Asks the human before a tool runs: [y] once · [a] always · [n] deny."""

    can_focus = True

    BINDINGS = [
        Binding("y", "once", "Run once"),
        Binding("a", "always", "Always allow"),
        Binding("n", "deny", "Deny"),
    ]

    DEFAULT_CSS = """
    ApprovalPrompt {
        height: auto;
        display: none;
        padding: 0 1;
        background: $surface;
        border: tall $warning;
    }
    ApprovalPrompt > .approval-title {
        height: 1;
        color: $warning;
        text-style: bold;
    }
    ApprovalPrompt > .approval-body {
        height: auto;
        max-height: 6;
        overflow-y: auto;
        color: $text-primary;
    }
    ApprovalPrompt > .approval-hint {
        height: 1;
        color: $muted;
    }
    """

    class Decided(Message):
        """The user answered the prompt."""

        def __init__(self, call_id: str, decision: str) -> None:
            super().__init__()
            self.call_id = call_id
            self.decision = decision

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.call_id: str = ""

    def compose(self):
        yield Static("", id="approval-title", classes="approval-title")
        yield Static("", id="approval-body", classes="approval-body")
        yield Static("y  run once     a  always allow     n  deny",
                     id="approval-hint", classes="approval-hint")

    def ask(self, call_id: str, name: str, args: dict, summary: str = "") -> None:
        """Show the prompt for a pending call."""
        self.call_id = call_id
        title = Text()
        title.append("approve ", style="bold yellow")
        title.append(name, style="bold yellow")
        self.query_one("#approval-title", Static).update(title)
        self.query_one("#approval-body", Static).update(summary or "")
        self.display = True

    def dismiss(self) -> None:
        """Hide the prompt."""
        self.display = False
        self.call_id = ""

    def decide(self, decision: str) -> None:
        """Send the answer up to the app."""
        if not self.call_id:
            return
        call_id = self.call_id
        self.dismiss()
        self.post_message(self.Decided(call_id, decision))

    # -- key handling ---------------------------------------------------------

    def action_once(self) -> None:
        self.decide("once")

    def action_always(self) -> None:
        self.decide("always")

    def action_deny(self) -> None:
        self.decide("deny")
