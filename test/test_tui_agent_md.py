"""Offline probe: AGENT.md comes from the PROJECT folder and shows up on top.

Run:  .venv/bin/python test/test_tui_agent_md.py   (from project root)
"""

import asyncio
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tui.app import HarnessApp  # noqa: E402

passed = failed = 0


def check(label, ok, detail=""):
    global passed, failed
    print(("ok  " if ok else "FAIL"), label, detail)
    passed += ok
    failed += not ok


async def probe(project: Path):
    """Boot the app on `project` and report what it picked up."""
    app = HarnessApp(project=str(project))
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        status = app.query_one("#status")
        result = {
            "badge": status.agent_md,
            "system": app.adapter.convo.history[0]["content"],
            "notes": [str(w.render()) for w in app.query(".note")],
        }
        await app.action_quit()
    return result


async def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="harness-agent-md-"))
    try:
        with_rules = root / "with-rules"
        with_rules.mkdir()
        (with_rules / "AGENT.md").write_text(
            "# Project rules\n\n- always use tabs\n- never touch build/\n",
            encoding="utf-8",
        )
        without = root / "without-rules"
        without.mkdir()

        # --- a project that has an AGENT.md -------------------------------
        got = await probe(with_rules)
        check("badge in the top bar", got["badge"] == "AGENT.md", f"({got['badge']!r})")
        check("AGENT.md is the system prompt", "always use tabs" in got["system"])
        check("the path is shown", any("AGENT.md loaded from" in n for n in got["notes"]))

        # --- a project that has none -------------------------------------
        got = await probe(without)
        check("no badge without an AGENT.md", got["badge"] == "", f"({got['badge']!r})")
        check("default prompt is used", "coding agent" in got["system"])
        check(
            "the harness' own AGENT.md does not leak in",
            "never touch build/" not in got["system"]
            and "Do not commit secrets" not in got["system"],
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
