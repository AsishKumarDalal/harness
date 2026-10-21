"""Offline probe: the model is a machine-wide choice, and skills load like
Claude Code's.

Run:  .venv/bin/python test/test_model_skills.py   (from project root)
"""

import asyncio
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
import safety  # noqa: E402
import tools  # noqa: E402

passed = failed = 0


def check(label, ok, detail=""):
    global passed, failed
    print(("ok  " if ok else "FAIL"), label, detail)
    passed += ok
    failed += not ok


def write_skill(folder: Path, name: str, description: str, body: str) -> None:
    skill_dir = folder / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n{body}\n",
        encoding="utf-8",
    )


def test_model_settings(root: Path) -> None:
    """The model choice is saved for the machine, not for a project."""
    settings = root / "settings.json"
    original = config.SETTINGS_PATH
    config.SETTINGS_PATH = settings
    try:
        before = config.MODEL
        message = config.set_model("gpt-4o-mini")
        check("set_model reports back", "gpt-4o-mini" in message, f"-> {message}")
        check("the choice is written to disk", settings.exists())
        data = json.loads(settings.read_text(encoding="utf-8"))
        check("the file holds the model", data.get("model") == "gpt-4o-mini", f"-> {data}")
        check("config.MODEL changed right away", config.MODEL == "gpt-4o-mini")
        check("the source is 'saved'", config.model_source() == "saved")

        # a fresh process must find the same model
        saved = json.loads(settings.read_text(encoding="utf-8"))
        check("a new run picks it up", saved.get("model") == config.get_model())

        # an empty name is refused
        check("an empty model is refused", "must not be empty" in config.set_model("  "))

        config.set_model(before)
    finally:
        config.SETTINGS_PATH = original


def test_llm_uses_the_current_model(root: Path) -> None:
    """llm.chat must read the model at call time, not at import time."""
    import llm

    seen = {}

    class FakeStream:
        def __iter__(self):
            return iter([])

        def close(self):
            pass

    class FakeCompletions:
        def create(self, **kwargs):
            seen.update(kwargs)
            return FakeStream()

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    llm._client = FakeClient()
    original = config.MODEL
    try:
        config.MODEL = "model-at-call-time"
        llm.chat([{"role": "user", "content": "hi"}])
        check("llm.chat uses the current model", seen.get("model") == "model-at-call-time",
              f"-> {seen.get('model')}")
    finally:
        llm._client = None
        config.MODEL = original


def test_skills(root: Path) -> None:
    """Skills are found in both scopes, listed in the prompt, and loadable."""
    project = root / "project"
    project.mkdir(parents=True, exist_ok=True)
    machine = root / "skills"      # HARNESS_HOME/skills
    machine.mkdir(parents=True, exist_ok=True)

    write_skill(project / ".harness" / "skills", "deploy",
                "How to deploy this app", "The secret phrase is BANANA-42.")
    write_skill(machine, "pdf", "Read PDF files", "Use pdftotext.")

    import skills

    original_start = config.START_DIR
    config.START_DIR = project
    original_machine = config.HARNESS_HOME
    config.HARNESS_HOME = root          # the machine scope lives in HARNESS_HOME
    try:
        rows = skills.list_skills()
        names = {row["name"]: row for row in rows}
        check("the project skill is found", "deploy" in names)
        check("the machine skill is found", "pdf" in names)
        check("the scope is right", names["deploy"]["scope"] == "project"
              and names["pdf"]["scope"] == "machine")
        check("the description comes from the front matter",
              names["deploy"]["description"] == "How to deploy this app")

        body = skills.load_skill("deploy")
        check("the body is loaded", "BANANA-42" in body, f"-> {body[:60]!r}")
        check("the front matter is not in the body", "description:" not in body)

        missing = skills.load_skill("nope")
        check("a missing skill explains itself", "no skill named" in missing
              and "deploy" in missing)

        from messages import default_system_prompt
        prompt = default_system_prompt()
        check("the system prompt lists the skills", "deploy" in prompt and "pdf" in prompt)
        check("the system prompt says how to load them", "skill" in prompt.lower())

        # the tool
        check("the skill tool is registered", "skill" in tools.REGISTRY)
        check("the skill tool is in the schema",
              any(t["function"]["name"] == "skill" for t in tools.SCHEMA))
        check("loading a skill is free (a read)", "skill" in safety.FREE_TOOLS)
        check("the tool returns the instructions",
              "BANANA-42" in tools.skill("deploy"))
    finally:
        config.START_DIR = original_start
        config.HARNESS_HOME = original_machine


async def test_tui_commands(root: Path) -> None:
    """The TUI: /model is machine-wide, /skills lists them."""
    from tui.app import HarnessApp

    project = root / "tui-project"
    project.mkdir(parents=True, exist_ok=True)
    write_skill(project / ".harness" / "skills", "deploy",
                "How to deploy this app", "The secret phrase is BANANA-42.")

    original_settings = config.SETTINGS_PATH
    original_model = config.MODEL
    config.SETTINGS_PATH = root / "settings.json"
    try:
        app = HarnessApp(project=str(project))
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            prompt = app.query_one("#prompt")

            await pilot.press(*"/skills")
            await pilot.press("enter")
            await pilot.pause(0.3)
            notes = [str(w.render()) for w in app.query(".note")]
            check("/skills lists them", any("deploy" in note for note in notes),
                  f"-> {notes[-1][:70] if notes else ''}")

            await pilot.press(*"/model gpt-4o-mini")
            await pilot.press("enter")
            await pilot.pause(0.3)
            check("/model changed the model", app.adapter.model == "gpt-4o-mini")
            saved = json.loads((root / "settings.json").read_text(encoding="utf-8"))
            check("/model saved it for the machine", saved.get("model") == "gpt-4o-mini",
                  f"-> {saved}")
            await app.action_quit()
    finally:
        config.SETTINGS_PATH = original_settings
        config.MODEL = original_model


async def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="harness-model-skills-"))
    try:
        test_model_settings(root)
        test_llm_uses_the_current_model(root)
        test_skills(root)
        await test_tui_commands(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
