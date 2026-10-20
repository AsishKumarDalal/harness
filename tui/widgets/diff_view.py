"""tui/widgets/diff_view.py — a file edit shown as a colored diff."""

from __future__ import annotations

from rich.text import Text
from textual.widgets import Static


def render_diff(diff: str, theme=None) -> Text:
    """Turn a unified diff into rich text: green added, red removed."""
    accent = getattr(theme, "accent", None) or "blue"
    success = getattr(theme, "success", None) or "green"
    error = getattr(theme, "error", None) or "red"
    muted = getattr(theme, "secondary", None) or "dim"
    text = Text()
    for line in diff.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            text.append(line + "\n", style=f"bold {accent}")
        elif line.startswith("@@"):
            text.append(line + "\n", style=f"bold {muted}")
        elif line.startswith("+"):
            text.append(line + "\n", style=success)
        elif line.startswith("-"):
            text.append(line + "\n", style=error)
        else:
            text.append(line + "\n", style="dim")
    return text


class DiffView(Static):
    """A read-only, colored diff."""

    DEFAULT_CSS = """
    DiffView {
        height: auto;
        max-height: 20;
        overflow-y: auto;
        padding: 0 1;
        background: $background;
        color: $text-primary;
    }
    """

    def __init__(self, diff: str, path: str = "", **kwargs) -> None:
        super().__init__(**kwargs)
        self.diff = diff
        self.path = path

    def on_mount(self) -> None:
        self.update(render_diff(self.diff, self.app.current_theme))
