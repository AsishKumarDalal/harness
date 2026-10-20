"""tui/widgets/prompt.py — the docked multiline input."""

from __future__ import annotations

from textual.binding import Binding
from textual.message import Message
from textual.widgets import TextArea


class PromptInput(TextArea):
    """A multiline prompt: Enter sends, Shift+Enter adds a newline."""

    BINDINGS = [
        Binding("enter", "submit", "Send", show=False, priority=True),
        Binding("shift+enter", "newline", "New line", show=False, priority=True),
    ]

    DEFAULT_CSS = """
    PromptInput {
        height: auto;
        min-height: 3;
        max-height: 12;
        padding: 0 1;
        border: tall $border;
        background: $surface;
        color: $text-primary;
    }
    PromptInput:focus {
        border: tall $accent;
    }
    """

    class Submitted(Message):
        """The user pressed Enter with a non-empty prompt."""

        def __init__(self, value: str) -> None:
            super().__init__()
            self.value = value

    def action_submit(self) -> None:
        value = self.text.strip()
        if not value:
            return
        self.post_message(self.Submitted(value))

    def action_newline(self) -> None:
        self.insert("\n")
