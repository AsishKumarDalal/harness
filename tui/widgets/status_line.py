"""tui/widgets/status_line.py — the top bar: model, session, dir, git branch."""

from __future__ import annotations

import subprocess
from pathlib import Path

from textual.app import ComposeResult
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
        padding: 0 1;
        color: $muted;
        background: $panel;
    }
    """

    model: reactive[str] = reactive("")
    session: reactive[str] = reactive("")
    working_dir: reactive[str] = reactive("")
    branch: reactive[str] = reactive("")

    def render(self):  # type: ignore[override]
        model = self.model or "—"
        session = self.session or "—"
        cwd = self.working_dir or "—"
        branch = self.branch or "no git"
        return f"{model}  │  {session}  │  {cwd}  │  {branch}"
