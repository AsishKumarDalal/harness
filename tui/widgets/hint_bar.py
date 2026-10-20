"""tui/widgets/hint_bar.py — the footer with the key hints."""

from __future__ import annotations

from textual.widgets import Static


class HintBar(Static):
    """Keybinding hints, always visible at the bottom."""

    DEFAULT_CSS = """
    HintBar {
        height: 1;
        padding: 0 1;
        color: $muted;
        background: $panel;
    }
    """

    def render(self):  # type: ignore[override]
        return (
            "enter send  ·  shift+enter newline  ·  esc interrupt  "
            "·  ctrl+p palette  ·  ctrl+c quit"
        )
