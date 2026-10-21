"""tui/widgets/status_line.py — the top bar: model, session, dir, git branch."""

from __future__ import annotations

import subprocess
from pathlib import Path

from rich.text import Text
from textual.reactive import reactive
from textual.widgets import Static


def git_branch(path: Path) -> str:
    """Current git branch of `path` (empty string when not a repo)."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(path),
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return ""
    if out.returncode != 0:
        return ""
    branch = out.stdout.strip()
    return "" if branch == "HEAD" else branch


class StatusBar(Static):
    """One line of context: model | session | cwd | branch."""

    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        padding: 0 2;
        color: $muted;
        background: $panel;
    }
    """

    model: reactive[str] = reactive("")
    session: reactive[str] = reactive("")
    working_dir: reactive[str] = reactive("")
    branch: reactive[str] = reactive("")
    agent_md: reactive[str] = reactive("")

    def render(self):  # type: ignore[override]
        """The model in the accent colour, the rest muted."""
        theme = self.app.current_theme
        accent = theme.accent or theme.primary
        muted = theme.secondary or "dim"
        loaded = theme.success or "green"

        text = Text()
        text.append(self.model or "—", style=accent)
        if self.agent_md:
            text.append("  ")
            text.append(self.agent_md, style=loaded)   # the project's AGENT.md
        text.append("  │  ", style=muted)
        text.append(self.session or "—")
        text.append("  │  ", style=muted)
        text.append(self.working_dir or "—")
        text.append("  │  ", style=muted)
        text.append(self.branch or "no git")
        return text
