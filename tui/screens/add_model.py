"""tui/screens/add_model.py — add a model that comes from another endpoint.

Two steps, like opencode's provider setup:

  1. the base url and the api key of the endpoint
  2. the models that endpoint offers - pick the one to use

The endpoint is remembered in $HARNESS_HOME/settings.json, so the model
works from every project on this machine. The api key is only ever written
to that file (mode 600), never to the project.
"""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

#: what the screen gives back: (model, base_url, api_key, models)
Result = tuple[str, str, str, list[str]]


class AddModelScreen(ModalScreen[Result | None]):
    """Ask for an endpoint, then ask which of its models to use."""

    DEFAULT_CSS = """
    AddModelScreen {
        align: center middle;
    }
    AddModelScreen > #add-model {
        width: 70%;
        max-width: 80;
        height: auto;
        max-height: 80%;
        background: $surface;
        border: solid $accent;
        padding: 1;
    }
    AddModelScreen > #add-model > #add-title {
        height: 1;
        color: $accent;
        text-style: bold;
    }
    AddModelScreen > #add-model > .add-label {
        height: 1;
        color: $muted;
    }
    AddModelScreen > #add-model > .add-input {
        height: 3;
        border: solid $border;
        background: $background;
    }
    AddModelScreen > #add-model > #add-hint {
        height: 1;
        color: $muted;
    }
    AddModelScreen > #add-model > #add-error {
        height: auto;
        color: $error;
    }
    AddModelScreen > #add-model > #add-options {
        height: auto;
        max-height: 12;
        background: $surface;
    }
    AddModelScreen > #add-model > #add-step-2 {
        display: none;
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
    ]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._base_url = ""
        self._api_key = ""
        self._models: list[str] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="add-model"):
            yield Static("add a new model", id="add-title")
            yield Static("base url", classes="add-label")
            yield Input(placeholder="https://api.openai.com/v1", id="add-url",
                        classes="add-input")
            yield Static("api key", classes="add-label")
            yield Input(placeholder="sk-…", id="add-key", password=True,
                        classes="add-input")
            yield Static("", id="add-error")
            yield Static("enter continue · esc cancel", id="add-hint")
            with Vertical(id="add-step-2"):
                yield Static("which model do you want?", classes="add-label")
                yield OptionList(id="add-options")
                yield Input(placeholder="or type a model name…", id="add-manual",
                            classes="add-input")
                yield Static("enter use it · esc cancel", id="add-hint2")

    def on_mount(self) -> None:
        self.query_one("#add-url", Input).focus()

    # ------------------------------------------------------------------
    # step 1: the endpoint
    # ------------------------------------------------------------------

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        if event.input.id == "add-url":
            self.query_one("#add-key", Input).focus()
            return
        if event.input.id == "add-key":
            self._fetch_models()
            return
        if event.input.id == "add-manual":
            self._use(event.value.strip())

    def _fetch_models(self) -> None:
        """Ask the endpoint which models it has."""
        base_url = self.query_one("#add-url", Input).value.strip()
        api_key = self.query_one("#add-key", Input).value.strip()
        if not base_url:
            self._error("a base url is needed")
            return
        if "://" not in base_url:
            base_url = "https://" + base_url
        self._base_url = base_url
        self._api_key = api_key

        import llm

        try:
            self._models = llm.list_models(base_url, api_key)
        except Exception as exc:
            self._models = []
            self._error(f"could not read the model list ({type(exc).__name__}: {exc})")
        else:
            if not self._models:
                self._error("the endpoint gave no models - type the name below")
            else:
                self._error("")

        self.query_one("#add-step-2", Vertical).display = True
        self.query_one("#add-step-2", Vertical).display = True
        options = self.query_one("#add-options", OptionList)
        options.clear_options()
        for name in self._models:
            options.add_option(Option(name, id=f"model:{name}"))
        if self._models:
            options.action_first()
            options.focus()
        else:
            self.query_one("#add-manual", Input).focus()

    def _error(self, message: str) -> None:
        self.query_one("#add-error", Static).update(message)

    # ------------------------------------------------------------------
    # step 2: which model
    # ------------------------------------------------------------------

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        if event.option.id and event.option.id.startswith("model:"):
            self._use(event.option.id.split(":", 1)[1])

    def _use(self, name: str) -> None:
        if not name:
            return
        self.dismiss((name, self._base_url, self._api_key, list(self._models)))

    def action_dismiss(self) -> None:
        self.dismiss(None)
