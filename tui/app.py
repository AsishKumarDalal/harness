"""tui/app.py — the chat screen: a dark, keyboard-first opencode-style TUI.

Layout (top to bottom):
    status line  →  scrollable chat history  →  docked multiline prompt
    →  key hints

The harness itself is untouched: everything here goes through
`tui.adapter.HarnessAdapter`.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import config
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, VerticalScroll
from textual.widgets import Markdown, Static

from .adapter import HarnessAdapter
from .events import (
    Thinking,
    Token,
    ToolCall,
    ToolResult,
    TurnDone,
    TurnEnd,
    TurnError,
)
from .theme import build_theme
from .widgets.hint_bar import HintBar
from .widgets.prompt import PromptInput
from .widgets.status_line import StatusBar, git_branch

#: how often the streaming text is repainted (seconds)
STREAM_FLUSH = 0.04

WELCOME = """[b]harness[/] — opencode-style TUI

Type a request and press enter."""


class HarnessApp(App[None]):
    """The harness, in a terminal."""

    CSS_PATH = "app.tcss"
    TITLE = "harness"
    SUB_TITLE = "opencode-style TUI"

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", priority=True),
        Binding("escape", "interrupt", "Interrupt", priority=True),
    ]

    def __init__(self, model: str | None = None, project: str | Path | None = None) -> None:
        super().__init__()
        # the theme comes from the app.tcss palette and must be live BEFORE
        # any widget CSS is resolved
        self.register_theme(build_theme())
        self.theme = "harness"
        self.adapter = HarnessAdapter(model=model, project=project)
        self._stream_text = ""
        self._thinking_text = ""
        self._stream_widget: Markdown | None = None
        self._thinking_widget: Static | None = None
        self._flush_scheduled = False
        self._last_flush = 0.0
        self._busy = False

    # ------------------------------------------------------------------
    # layout
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield StatusBar(id="status")
        with VerticalScroll(id="chat"):
            yield Static(WELCOME, id="welcome", classes="welcome")
        with Container(id="prompt-dock"):
            yield PromptInput(
                id="prompt",
                placeholder="Ask anything…  (enter to send, shift+enter for a new line)",
            )
        yield HintBar(id="hints")

    def on_mount(self) -> None:
        self.adapter.new_session()
        self._refresh_status()
        self.query_one("#prompt", PromptInput).focus()
        self._note(f"session {self.adapter.session_id}")

    # ------------------------------------------------------------------
    # status
    # ------------------------------------------------------------------

    def _refresh_status(self) -> None:
        status = self.query_one("#status", StatusBar)
        status.model = self.adapter.model
        status.working_dir = str(config.START_DIR)
        status.branch = git_branch(config.START_DIR)
        title = self.adapter.session_id or "—"
        status.session = title[:40]

    def _note(self, text: str) -> None:
        """Small note in the chat area."""
        chat = self.query_one("#chat", VerticalScroll)
        chat.mount(Static(text, classes="note", markup=False))
        chat.scroll_end(animate=False)

    # ------------------------------------------------------------------
    # sending
    # ------------------------------------------------------------------

    def on_prompt_input_submitted(self, event: PromptInput.Submitted) -> None:
        """Enter was pressed in the prompt."""
        event.stop()
        text = event.value
        self.query_one("#prompt", PromptInput).load_text("")
        self._send(text)

    def _send(self, text: str) -> None:
        if self._busy:
            self._note("busy — esc to interrupt")
            return
        chat = self.query_one("#chat", VerticalScroll)
        chat.mount(Static(text, classes="user-message", markup=False))
        chat.scroll_end(animate=False)
        self._busy = True
        self._run_turn(text)

    @work(exclusive=True)
    async def _run_turn(self, text: str) -> None:
        """Stream one turn, rendering events as they arrive."""
        async for event in self.adapter.send(text):
            self._handle_event(event)
        self._busy = False

    # ------------------------------------------------------------------
    # events
    # ------------------------------------------------------------------

    def _handle_event(self, event: Any) -> None:
        if isinstance(event, Token):
            self._on_token(event.text)
        elif isinstance(event, Thinking):
            self._on_thinking(event.text)
        elif isinstance(event, ToolCall):
            self._note(f"tool: {event.name}")
        elif isinstance(event, ToolResult):
            pass
        elif isinstance(event, TurnDone):
            self._on_done(event.content)
        elif isinstance(event, TurnError):
            self._note(f"error: {event.message}")
        elif isinstance(event, TurnEnd):
            self._flush_stream(force=True)
            self._busy = False

    def _on_token(self, text: str) -> None:
        self._stream_text += text
        self._flush_stream()

    def _flush_stream(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and (now - self._last_flush) < STREAM_FLUSH:
            if not self._flush_scheduled:
                self._flush_scheduled = True
                self.set_timer(STREAM_FLUSH, lambda: self._flush_stream(force=True))
            return
        self._flush_scheduled = False
        self._last_flush = now
        if not self._stream_text:
            return
        chat = self.query_one("#chat", VerticalScroll)
        if self._stream_widget is None:
            self._stream_widget = Markdown(self._stream_text, classes="assistant-message")
            chat.mount(self._stream_widget)
        else:
            self._stream_widget.update(self._stream_text)
        chat.scroll_end(animate=False)

    def _on_thinking(self, text: str) -> None:
        self._thinking_text += text
        chat = self.query_one("#chat", VerticalScroll)
        if self._thinking_widget is None:
            self._thinking_widget = Static("", classes="thinking")
            chat.mount(self._thinking_widget)
        self._thinking_widget.update(self._thinking_text)
        chat.scroll_end(animate=False)

    def _on_done(self, content: str) -> None:
        self._flush_stream(force=True)
        self._stream_text = ""
        self._stream_widget = None
        self._thinking_text = ""
        self._thinking_widget = None

    # ------------------------------------------------------------------
    # actions
    # ------------------------------------------------------------------

    def action_interrupt(self) -> None:
        """Esc — stop the running generation."""
        if self._busy:
            self.adapter.cancel()
            self._note("interrupted")
