"""tui/screens/model_screen.py — the /model window.

Shows the model in use right now, the models this machine knows about, and
an input where a new model name can be typed (any OpenAI-compatible name:
gpt-4o, gpt-4o-mini, k2-horizon-…, …).

The choice is machine-wide: it is saved in $HARNESS_HOME/settings.json and
follows you from project to project.
"""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option


class ModelScreen(ModalScreen[str | None]):
    """Pick a model, or type a new one."""

    DEFAULT_CSS = """
    ModelScreen {
        align: center middle;
    }
    ModelScreen > #model-window {
        width: 70%;
        max-width: 80;
        height: auto;
        max-height: 80%;
        background: $surface;
        border: solid $accent;
        padding: 1;
    }
    ModelScreen > #model-window > #model-title {
        height: 1;
        color: $accent;
        text-style: bold;
    }
    ModelScreen > #model-window > #model-current {
        height: 1;
        color: $text;
    }
    ModelScreen > #model-window > #model-current-label {
        color: $muted;
    }
    ModelScreen > #model-window > #model-input {
        height: 3;
        border: solid $border;
        background: $background;
    }
    ModelScreen > #model-window > #model-hint {
        height: 1;
        color: $muted;
    }
    ModelScreen > #model-window > #model-options {
        height: auto;
        max-height: 12;
        background: $surface;
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
    ]

    def __init__(self, current: str, models: list[str], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._current = current
        self._models = [m for m in models if m]

    def compose(self) -> ComposeResult:
        with Vertical(id="model-window"):
            yield Static("model", id="model-title")
            yield Static("", id="model-current")
            yield Input(placeholder="type a model name and press enter…",
                        id="model-input")
            yield Static("enter set · tab pick from the list · esc close",
                         id="model-hint")
            yield OptionList(id="model-options")

    def on_mount(self) -> None:
        self.query_one("#model-current", Static).update(
            f"current: {self._current}"
        )
        self._fill_options("")
        self.query_one("#model-input", Input).focus()

    # ------------------------------------------------------------------
    # the list of known models
    # ------------------------------------------------------------------

    def _fill_options(self, needle: str) -> None:
        options = self.query_one("#model-options", OptionList)
        options.clear_options()
        needle = needle.strip().lower()
        known = [m for m in self._models if not needle or needle in m.lower()]
        if not known:
            return
        options.add_option(Option("── known models ──", disabled=True))
        for name in known:
            marker = " (current)" if name == self._current else ""
            options.add_option(Option(f"{name}{marker}", id=f"model:{name}"))

    # ------------------------------------------------------------------
    # input
    # ------------------------------------------------------------------

    def on_input_changed(self, event: Input.Changed) -> None:
        event.stop()
        self._fill_options(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """A new model name was typed: use it."""
        event.stop()
        name = event.value.strip()
        if not name:
            return
        self.dismiss(name)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        if event.option.id and event.option.id.startswith("model:"):
            self.dismiss(event.option.id.split(":", 1)[1])

    def on_key(self, event) -> None:
        """Tab moves between the input and the list."""
        if event.key == "tab":
            event.stop()
            event.prevent_default()
            self.query_one("#model-options", OptionList).focus()
        elif event.key == "shift+tab":
            event.stop()
            event.prevent_default()
            self.query_one("#model-input", Input).focus()

    def action_dismiss(self) -> None:
        self.dismiss(None)
