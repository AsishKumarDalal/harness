"""skills.py — loadable instruction sets, the way Claude Code does it.

A skill is a folder with a SKILL.md inside:

    ~/.harness/skills/pdf/SKILL.md            this machine, every project
    <project>/.harness/skills/pdf/SKILL.md    this project only

SKILL.md starts with a little front matter:

    ---
    name: pdf
    description: Extract text and tables from PDF files
    ---

    # Working with PDFs
    ...the instructions the model should follow when the task fits...

The model is told which skills exist (name + description) in its system
prompt and loads the full instructions on demand with the `skill` tool -
so a skill costs nothing until it is actually needed.

The project scope wins over the machine scope when both have the same name.
"""

from __future__ import annotations

import config
from pathlib import Path

#: how much of a skill is handed to the model
MAX_SKILL_CHARS = 20_000       # a skill is instructions, not a data dump


def global_dir() -> Path:
    """The machine scope: every project on this machine sees these."""
    return config.HARNESS_HOME / "skills"


def project_dir() -> Path:
    """The project scope: only the folder the agent works on sees these."""
    return config.START_DIR / ".harness" / "skills"


# kept for convenience / backwards compatibility
GLOBAL_DIR = global_dir()
PROJECT_DIR = project_dir()


def _parse(text: str) -> tuple[dict, str]:
    """Split a SKILL.md into (front matter, body)."""
    text = text.lstrip("﻿")
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    meta: dict[str, str] = {}
    for line in parts[1].strip().splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        meta[key.strip().lower()] = value.strip().strip("'\"")
    return meta, parts[2].lstrip("\n")


def _read(path: Path) -> tuple[dict, str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}, ""
    return _parse(text)


def skill_dirs() -> list[tuple[str, Path]]:
    """The skill folders to look in: (scope, folder), project last (wins)."""
    return [("machine", global_dir()), ("project", project_dir())]


def list_skills() -> list[dict]:
    """Every skill that can be loaded: name, description, scope, path."""
    found: dict[str, dict] = {}
    for scope, folder in skill_dirs():
        if not folder.is_dir():
            continue
        for entry in sorted(folder.iterdir()):
            skill_file = entry / "SKILL.md"
            if not skill_file.is_file():
                skill_file = entry / "skill.md"
                if not skill_file.is_file():
                    continue
            meta, body = _read(skill_file)
            name = meta.get("name") or entry.name
            description = meta.get("description") or _first_line(body)
            found[name] = {
                "name": name,
                "description": description,
                "scope": scope,
                "path": str(skill_file),
            }
    return list(found.values())


def _first_line(body: str) -> str:
    """The description falls back to the first heading of the body."""
    for line in body.splitlines():
        line = line.strip()
        if line:
            return line.lstrip("# ").strip()[:120]
    return ""


def load_skill(name: str) -> str:
    """The instructions of one skill (its body, front matter removed)."""
    name = (name or "").strip()
    if not name:
        return "error: skill name is empty"
    wanted = name.lower().replace("_", "-")
    for scope, folder in reversed(skill_dirs()):     # project first: it wins
        if not folder.is_dir():
            continue
        for entry in sorted(folder.iterdir()):
            skill_file = entry / "SKILL.md"
            if not skill_file.is_file():
                skill_file = entry / "skill.md"
                if not skill_file.is_file():
                    continue
            meta, body = _read(skill_file)
            skill_name = (meta.get("name") or entry.name).lower().replace("_", "-")
            if skill_name != wanted:
                continue
            if len(body) > MAX_SKILL_CHARS:
                body = body[:MAX_SKILL_CHARS] + "\n...[truncated]"
            header = f"# skill: {meta.get('name') or entry.name}  ({scope})"
            return f"{header}\n\n{body}"
    known = ", ".join(s["name"] for s in list_skills()) or "(none)"
    return f"error: no skill named '{name}'. available skills: {known}"


def prompt_line() -> str:
    """The line that tells the model which skills exist (empty if none)."""
    rows = list_skills()
    if not rows:
        return ""
    lines = [
        "You can load a skill when the task fits it (the skill tool gives you "
        "its full instructions):",
    ]
    for row in rows:
        lines.append(f"- {row['name']}: {row['description']}")
    return "\n".join(lines)
