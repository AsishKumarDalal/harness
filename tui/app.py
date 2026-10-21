"""tui/app.py — the chat screen: a dark, keyboard-first opencode-style TUI.

Layout (top to bottom):
    status line  →  scrollable chat history  →  docked multiline prompt
    →  key hints

The harness itself is untouched: everything here goes through
`tui.adapter.HarnessAdapter`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import config
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.widgets import Markdown, Static

from .adapter import HarnessAdapter
from .commands import Command, is_known, parse_command
from .events import (
    ApprovalNeeded,
    Thinking,
    Token,
    ToolCall,
    ToolDiff,
    ToolResult,
    TurnDone,
    TurnEnd,
    TurnError,
)
from .screens.add_model import AddModelScreen
from .screens.model_screen import ModelScreen
from .screens.palette import PaletteScreen
from .theme import build_theme
from .widgets.approval import ApprovalPrompt
from .widgets.chat_area import ChatArea
from .widgets.hint_bar import HintBar
from .widgets.prompt import PromptInput
from .widgets.status_line import StatusBar, git_branch
from .widgets.tool_block import ToolBlock

#: how often the streaming text is repainted (seconds)
STREAM_FLUSH = 0.04

WELCOME = """[b]harness[/] — opencode-style TUI

Type a request and press enter.  /help for commands, ctrl+p for the palette."""


HELP_TEXT = """[b]commands[/]
  /new title         start a fresh session
  /sessions          list stored sessions
  /model name        the model window (or set a model directly)
  /skills            list the skills that can be loaded
  /clear             clear the screen (keeps the session)
  /help              this text

[b]keys[/]
  enter send · shift+enter newline · esc interrupt · ctrl+p palette · ctrl+c quit"""


class HarnessApp(App[None]):
    """The harness, in a terminal."""

    CSS_PATH = "app.tcss"
    TITLE = "harness"
    SUB_TITLE = "opencode-style TUI"

    BINDINGS = [
        Binding("ctrl+p", "palette", "Palette", priority=True),
        Binding("ctrl+c", "quit", "Quit", priority=True),
        # no priority: an open modal (the palette) must get Esc first
        Binding("escape", "interrupt", "Interrupt"),
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
        self._appended = 0             # how much of the answer is in the widget
        self._tool_blocks: dict[str, ToolBlock] = {}
        self._flush_scheduled = False
        self._busy = False

    # ------------------------------------------------------------------
    # layout
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield StatusBar(id="status")
        with ChatArea(id="chat"):
            yield Static(WELCOME, id="welcome", classes="welcome")
        yield ApprovalPrompt(id="approval")
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
        agent_md = self.adapter.agent_md()
        if agent_md:
            lines = len(agent_md.splitlines())
            self._note(f"AGENT.md loaded from {config.START_DIR} ({lines} lines)")

    # ------------------------------------------------------------------
    # status
    # ------------------------------------------------------------------

    def _refresh_status(self) -> None:
        status = self.query_one("#status", StatusBar)
        status.model = self.adapter.model
        status.working_dir = str(config.START_DIR)
        status.branch = git_branch(config.START_DIR)
        status.session = self.adapter.session_label()[:40]
        status.agent_md = self.adapter.agent_md_name()

    def _note(self, text: str, markup: bool = False, extra: str = "") -> None:
        """Small note in the chat area (markup only for our own text)."""
        chat = self.query_one("#chat", ChatArea)
        chat.mount(Static(text, classes=f"note {extra}".strip(), markup=markup))

    # ------------------------------------------------------------------
    # scrolling
    # ------------------------------------------------------------------

    def on_chat_area_follow_changed(self, event: ChatArea.FollowChanged) -> None:
        """The user scrolled: follow the stream only while at the bottom."""
        event.stop()
        if event.follow:
            # back at the bottom - pin the view again
            self._follow_down()

    def _follow_down(self) -> None:
        """Pin the view to the last line.

        The chat area is *anchored*: the compositor keeps the bottom line in
        place while the content grows, in the same frame it is laid out. A
        manual scroll_end() is deferred to the next refresh, so the new text
        would be painted before the view caught up - that is the jumping.
        """
        chat = self.query_one("#chat", ChatArea)
        chat.follow()

    # ------------------------------------------------------------------
    # sending
    # ------------------------------------------------------------------

    def on_prompt_input_submitted(self, event: PromptInput.Submitted) -> None:
        """Enter was pressed in the prompt."""
        event.stop()
        text = event.value
        self.query_one("#prompt", PromptInput).load_text("")
        command = parse_command(text)
        if command is not None:
            self._run_command(command)
            return
        self._send(text)

    def _send(self, text: str) -> None:
        if self._busy:
            self._note("busy — esc to interrupt")
            return
        chat = self.query_one("#chat", ChatArea)
        chat.follow()              # a new turn starts at the bottom again
        chat.mount(Static(text, classes="user-message", markup=False))
        self._busy = True
        self._run_turn(text)

    @work(exclusive=True)
    async def _run_turn(self, text: str) -> None:
        """Stream one turn, rendering events as they arrive."""
        async for event in self.adapter.send(text):
            await self._handle_event(event)
        self._busy = False

    # ------------------------------------------------------------------
    # events
    # ------------------------------------------------------------------

    async def _handle_event(self, event: Any) -> None:
        if isinstance(event, Token):
            self._on_token(event.text)
        elif isinstance(event, Thinking):
            self._on_thinking(event.text)
        elif isinstance(event, ToolCall):
            await self._on_tool_call(event)
        elif isinstance(event, ToolResult):
            self._on_tool_result(event)
        elif isinstance(event, ToolDiff):
            self._on_tool_diff(event)
        elif isinstance(event, ApprovalNeeded):
            self._on_approval(event)
        elif isinstance(event, TurnDone):
            await self._on_done(event.content)
        elif isinstance(event, TurnError):
            self._note(f"error: {event.message}")
        elif isinstance(event, TurnEnd):
            await self._flush_stream()
            self._busy = False

    def _on_token(self, text: str) -> None:
        self._stream_text += text
        self._schedule_flush()

    def _schedule_flush(self) -> None:
        """Repaint the answer at most every STREAM_FLUSH seconds."""
        if self._flush_scheduled:
            return
        self._flush_scheduled = True
        self.set_timer(STREAM_FLUSH, self._flush_stream)

    async def _flush_stream(self) -> None:
        """Add the new text to the answer widget.

        The answer is *appended*, not rebuilt. Rebuilding meant re-parsing
        the whole answer and remounting every block on every flush, which
        got slower the longer the answer got (400ms a flush after 1000
        lines) - the screen then crawled behind the stream and jumped in
        big steps. Appending only touches the last block, so a flush costs
        the same at the end of a long answer as at the start.
        """
        self._flush_scheduled = False
        chat = self.query_one("#chat", ChatArea)

        if self._thinking_text and self._thinking_widget is None:
            self._thinking_widget = Static("", classes="thinking")
            await chat.mount(self._thinking_widget)
        if self._thinking_widget is not None:
            self._thinking_widget.update(self._thinking_text)

        if not self._stream_text:
            return
        if self._stream_widget is None:
            self._stream_widget = Markdown("", classes="assistant-message")
            await chat.mount(self._stream_widget)
            self._appended = 0
        if len(self._stream_text) <= self._appended:
            return
        await self._stream_widget.append(self._stream_text[self._appended:])
        self._appended = len(self._stream_text)

    def _on_thinking(self, text: str) -> None:
        """Collect the reasoning - it is repainted together with the answer."""
        self._thinking_text += text
        self._schedule_flush()

    async def _on_done(self, content: str) -> None:
        await self._flush_stream()
        self._stream_text = ""
        self._stream_widget = None
        self._appended = 0
        self._thinking_text = ""
        self._thinking_widget = None

    # ------------------------------------------------------------------
    # tool calls
    # ------------------------------------------------------------------

    async def _on_tool_call(self, event: ToolCall) -> None:
        """A compact block per tool call."""
        chat = self.query_one("#chat", ChatArea)
        block = ToolBlock(event.call_id, event.name, event.args)
        self._tool_blocks[event.call_id] = block
        await chat.mount(block)

    def _on_tool_result(self, event: ToolResult) -> None:
        block = self._tool_blocks.get(event.call_id)
        if block is None:
            return
        block.set_status(event.status)
        block.set_output(event.output)

    def _on_tool_diff(self, event: ToolDiff) -> None:
        block = self._tool_blocks.get(event.call_id)
        if block is not None:
            block.add_diff(event.diff, event.path)

    # ------------------------------------------------------------------
    # approvals
    # ------------------------------------------------------------------

    def _on_approval(self, event: ApprovalNeeded) -> None:
        """Ask before a tool that needs a human yes."""
        prompt = self.query_one("#approval", ApprovalPrompt)
        prompt.ask(event.call_id, event.name, event.args, event.summary)
        prompt.focus()                      # y / a / n go to the prompt

    def on_approval_prompt_decided(self, event: ApprovalPrompt.Decided) -> None:
        event.stop()
        self.adapter.resolve_approval(event.call_id, event.decision)
        self.query_one("#prompt", PromptInput).focus()

    # ------------------------------------------------------------------
    # actions
    # ------------------------------------------------------------------

    def action_interrupt(self) -> None:
        """Esc — stop the running generation."""
        if self._busy:
            self.adapter.cancel()
            self._note("interrupted")

    def action_palette(self) -> None:
        """Ctrl+P — switch session or model."""
        rows = self.adapter.list_sessions()
        models = self.adapter.known_models()
        self.push_screen(PaletteScreen(rows, models), self._on_palette_choice)

    def _on_palette_choice(self, choice: str | None) -> None:
        """A session or a model was picked in the palette."""
        if not choice:
            return
        kind, _, value = choice.partition(":")
        if kind == "session":
            try:
                history = self.adapter.resume(value)
            except ValueError as exc:
                self._note(str(exc))
                return
            self._clear_chat()
            self._replay(history)
            self._refresh_status()
        elif kind == "model":
            self._set_model(value)

    def _on_model_choice(self, value: str | None) -> None:
        """A model was picked (or typed) in the /model window."""
        if not value:
            return
        if value == "__add__":
            self.push_screen(AddModelScreen(), self._on_new_model)
            return
        self._set_model(value)

    def _on_new_model(self, result: Any) -> None:
        """A new endpoint was set up: remember it and use one of its models."""
        if not result:
            return
        model, base_url, api_key, models = result
        key = config.save_provider(
            config.provider_key_for(base_url), base_url, api_key, models
        )
        config.set_model_provider(model, key)
        self._set_model(model)
        self._note(f"endpoint {key} saved for this machine")

    def _set_model(self, value: str) -> None:
        """Switch the model and remember it for this machine."""
        self.adapter.model = value
        config.set_model(value)
        self._refresh_status()
        self._note(f"model: {value}  (saved for this machine)")

    # ------------------------------------------------------------------
    # slash commands
    # ------------------------------------------------------------------

    def _run_command(self, command: Command) -> None:
        """Run a slash command (never reaches the model)."""
        if not is_known(command):
            self._note(f"unknown command /{command.name} — try /help")
            return
        if command.name == "new":
            self.adapter.new_session(command.arg or None)
            self._clear_chat()
            self._refresh_status()
            self._note(f"session {self.adapter.session_id}")
        elif command.name == "sessions":
            self._show_sessions()
        elif command.name == "model":
            if command.arg:
                # the model is a machine-wide choice: it follows you everywhere
                self._set_model(command.arg)
            else:
                self.push_screen(
                    ModelScreen(self.adapter.model, self.adapter.known_models()),
                    self._on_model_choice,
                )
        elif command.name == "skills":
            self._show_skills()
        elif command.name == "clear":
            self._clear_chat()
        elif command.name == "help":
            self._note(HELP_TEXT, markup=True, extra="help")

    def _show_skills(self) -> None:
        """List the skills that can be loaded."""
        import skills

        rows = skills.list_skills()
        if not rows:
            self._note(
                f"no skills yet — put them in {skills.global_dir()}/<name>/SKILL.md "
                f"or {skills.project_dir()}/<name>/SKILL.md"
            )
            return
        lines = [f"{row['name']}  [{row['scope']}]  {row['description']}" for row in rows]
        self._note("\n".join(lines))

    def _show_sessions(self) -> None:
        """List the stored sessions."""
        rows = self.adapter.list_sessions()
        if not rows:
            self._note("no sessions yet")
            return
        lines = [f"{r['id']}  {(r['title'] or 'untitled')[:40]}" for r in rows]
        self._note("\n".join(lines))

    # ------------------------------------------------------------------
    # chat helpers
    # ------------------------------------------------------------------

    def _clear_chat(self) -> None:
        """Empty the chat area (the session itself is untouched)."""
        chat = self.query_one("#chat", ChatArea)
        chat.remove_children()
        self._stream_text = ""
        self._stream_widget = None
        self._appended = 0
        self._thinking_text = ""
        self._thinking_widget = None
        self._tool_blocks.clear()

    def _replay(self, history: list[dict]) -> None:
        """Re-render a resumed session."""
        chat = self.query_one("#chat", ChatArea)
        for message in history:
            role = message.get("role")
            content = (message.get("content") or "").strip()
            if role == "user" and content:
                chat.mount(Static(content, classes="user-message", markup=False))
            elif role == "assistant" and content:
                chat.mount(Markdown(content, classes="assistant-message"))
        self._follow_down()
