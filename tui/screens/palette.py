"""tui/screens/palette.py — Ctrl+P: switch session or model."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option


class PaletteScreen(ModalScreen[str | None]):
    """A fuzzy-ish palette: sessions and models, filtered as you type."""

    DEFAULT_CSS = """
    PaletteScreen {
        align: center middle;
    }
    PaletteScreen > #palette {
        width: 70%;
        max-width: 90;
        height: auto;
        max-height: 70%;
        background: $surface;
        border: round $accent;
        padding: 1;
    }
    PaletteScreen > #palette > #palette-title {
        height: 1;
        color: $accent;
        text-style: bold;
    }
    PaletteScreen > #palette > #palette-filter {
        height: 3;
        border: tall $border;
    }
    PaletteScreen > #palette > #palette-options {
        height: auto;
        max-height: 18;
        background: $surface;
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
    ]

    def __init__(self, sessions: list[dict], models: list[str], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._sessions = sessions
        self._models = models

    def compose(self) -> ComposeResult:
        with Vertical(id="palette"):
            yield Static("switch session / model", id="palette-title")
            yield Input(placeholder="filter…", id="palette-filter")
            yield OptionList(id="palette-options")

    def on_mount(self) -> None:
        self._rebuild("")
        self.query_one("#palette-filter", Input).focus()

    def _rebuild(self, needle: str) -> None:
        options = self.query_one("#palette-options", OptionList)
        options.clear_options()
        needle = needle.lower().strip()

        def matches(*parts: str) -> bool:
            return not needle or any(needle in p.lower() for p in parts)

        if self._sessions:
            options.add_option(Option("── sessions ──", disabled=True))
            for row in self._sessions:
                title = row.get("title") or "untitled"
                if matches(str(row.get("id")), title):
                    options.add_option(
                        Option(f"{title[:38]:38}  {row.get('id')}", id=f"session:{row['id']}")
                    )
        if self._models:
            options.add_option(Option("── models ──", disabled=True))
            for model in self._models:
                if matches(model):
                    options.add_option(Option(model, id=f"model:{model}"))

        options.action_first()          # highlight the first real entry

    def on_input_changed(self, event: Input.Changed) -> None:
        event.stop()
        self._rebuild(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Enter in the filter picks the highlighted entry."""
        event.stop()
        self.query_one("#palette-options", OptionList).action_select()

    def on_key(self, event) -> None:
        """Arrow keys move the list even while the filter has focus."""
        options = self.query_one("#palette-options", OptionList)
        if event.key in ("down", "up", "home", "end"):
            event.stop()
            event.prevent_default()
            {
                "down": options.action_cursor_down,
                "up": options.action_cursor_up,
                "home": options.action_first,
                "end": options.action_last,
            }[event.key]()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self.dismiss(event.option.id)

    def action_dismiss(self) -> None:
        self.dismiss(None)
