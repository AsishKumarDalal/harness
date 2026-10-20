"""tui/widgets/tool_block.py — one compact, collapsible block per tool call."""

from __future__ import annotations

from rich.text import Text
from textual.containers import Vertical
from textual.widgets import Static

from .diff_view import DiffView, render_diff
from ..theme import status_color

#: status -> label
STATUS_LABEL = {
    "running": "running",
    "done": "done",
    "failed": "failed",
    "denied": "denied",
}


def call_summary(name: str, args: dict) -> str:
    """The short "what did it do" line under the tool name."""
    if name == "run_command":
        return str(args.get("command", "")).strip()
    if name in ("write_file", "edit_file", "read_file"):
        return str(args.get("path", ""))
    if name == "delegate":
        tasks = args.get("tasks") or []
        goals = [str(t.get("goal", "")).strip() for t in tasks if isinstance(t, dict)]
        return f"{len(tasks)} task(s): " + "; ".join(goals[:2])[:120]
    for key in ("needle", "query", "path", "command"):
        if key in args:
            return str(args[key])[:120]
    return ""


class ToolBlock(Vertical):
    """A tool call: one-line header, expandable body with output and diff."""

    DEFAULT_CSS = """
    ToolBlock {
        height: auto;
        margin: 0 0 1 0;
    }
    ToolBlock > .tool-header {
        height: 1;
        padding: 0 1;
    }
    ToolBlock > .tool-body {
        height: auto;
        max-height: 24;
        overflow-y: auto;
        padding: 0 1;
    }
    ToolBlock > .tool-body > .tool-output {
        height: auto;
        max-height: 20;
        overflow-y: auto;
        color: $muted;
    }
    """

    def __init__(self, call_id: str, name: str, args: dict, **kwargs) -> None:
        super().__init__(**kwargs)
        self.call_id = call_id
        self.tool_name = name          # `name` is taken by Textual's Widget
        self.args = args
        self.status = "running"
        self.output = ""
        self._expanded = False

    # -- layout ---------------------------------------------------------

    def compose(self):
        yield Static("", id="header", classes="tool-header")
        yield Vertical(id="body", classes="tool-body")

    def on_mount(self) -> None:
        self._render_header()
        self.query_one("#body", Vertical).display = False

    # -- content --------------------------------------------------------

    def set_status(self, status: str) -> None:
        """running | done | failed | denied."""
        self.status = status
        self._render_header()

    def set_output(self, output: str) -> None:
        """Attach the tool's output to the body."""
        self.output = output
        body = self.query_one("#body", Vertical)
        if not output:
            return
        static = Static(render_output(output), classes="tool-output")
        body.mount(static)
        if not self._expanded:
            self._expanded = True
            body.display = True

    def add_diff(self, diff: str, path: str = "") -> None:
        """Attach a colored diff to the body."""
        body = self.query_one("#body", Vertical)
        body.mount(DiffView(diff, path))
        if not self._expanded:
            self._expanded = True
            body.display = True

    def toggle(self) -> None:
        """Expand/collapse the body."""
        body = self.query_one("#body", Vertical)
        self._expanded = not self._expanded
        body.display = self._expanded

    def on_click(self, event) -> None:
        """Clicking the header expands/collapses the body."""
        event.stop()
        self.toggle()

    # -- rendering ------------------------------------------------------

    def _render_header(self) -> None:
        try:
            header = self.query_one("#header", Static)
        except Exception:
            return
        label = STATUS_LABEL.get(self.status, "running")
        theme = self.app.current_theme
        colour = status_color(self.app, self.status)
        muted = theme.secondary or "dim"
        text = Text()
        text.append("● ", style=colour)
        text.append(self.tool_name, style="bold")
        summary = call_summary(self.tool_name, self.args)
        if summary:
            text.append("  ")
            text.append(summary, style=muted)
        text.append("  ·  ")
        text.append(label, style=colour)
        header.update(text)


def render_output(output: str) -> Text:
    """Tool output as dim, plain text (no markup surprises)."""
    text = Text()
    for line in output.splitlines()[:200]:
        text.append(line + "\n", style="dim")
    return text
