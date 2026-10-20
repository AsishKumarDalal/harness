"""tui/theme.py — build the Textual theme from the palette in app.tcss.

`app.tcss` is the single source of truth for every colour. Textual's own
theme variables (used by built-in widgets: Markdown, OptionList, scrollbars)
are derived from that palette here, so re-theming means editing app.tcss only.

The palette variables are prefixed `$h-` on purpose: a CSS variable that
shares a name with a Textual theme variable (`$panel`, `$surface`, ...) would
be defined twice and break Textual's stylesheet parsing.
"""

from __future__ import annotations

import re
from pathlib import Path

from textual.theme import Theme

CSS_PATH = Path(__file__).resolve().parent / "app.tcss"

#: `$h-name: value;` declarations in app.tcss
_VAR_RE = re.compile(r"^\s*\$h-([a-z0-9-]+)\s*:\s*([^;]+);", re.MULTILINE)


def read_palette(css_path: Path | str = CSS_PATH) -> dict[str, str]:
    """The `$h-*` variables of app.tcss, as a plain dict."""
    source = Path(css_path).read_text(encoding="utf-8")
    return {name: value.strip() for name, value in _VAR_RE.findall(source)}


def status_color(app, status: str) -> str:
    """The colour for a tool status: running | done | failed | denied."""
    theme = app.current_theme
    return {
        "running": theme.accent or theme.primary,
        "done": theme.success or theme.primary,
        "failed": theme.error or theme.primary,
        "denied": theme.warning or theme.primary,
    }.get(status, theme.primary)


def build_theme(palette: dict[str, str] | None = None) -> Theme:
    """A Textual theme built from the app.tcss palette."""
    colors = palette if palette is not None else read_palette()
    return Theme(
        name="harness",
        primary=colors.get("accent", "#7aa2f7"),
        secondary=colors.get("muted", "#64748b"),
        accent=colors.get("accent", "#7aa2f7"),
        warning=colors.get("warning", "#e3b341"),
        error=colors.get("error", "#ff7b72"),
        success=colors.get("success", "#7ee787"),
        foreground=colors.get("text", "#c7d2e0"),
        background=colors.get("bg", "#0b0f14"),
        surface=colors.get("surface", "#111823"),
        panel=colors.get("panel", "#0d131b"),
        dark=True,
        variables={
            "text": colors.get("text", "#c7d2e0"),
            "muted": colors.get("muted", "#64748b"),
            "border": colors.get("border", "#1d2733"),
        },
    )
