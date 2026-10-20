"""Offline probe: the chat must follow the stream and never jump around.

Run:  .venv/bin/python test/test_tui_scroll.py   (from project root)

Regression test for the jumping view: the answer widget was rebuilt
before the scroll, so the scroll used the height the content had BEFORE
the new text arrived. The view was left short of the bottom and the next
flush yanked it down again - up and down, over and over.
"""

import asyncio
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tui.app import HarnessApp  # noqa: E402

CHUNKS = [
    "Here is a short answer.\n\n",
    "Here is a short answer.\n\n- first item\n",
    "Here is a short answer.\n\n- first item\n- second item\n",
    "Here is a short answer.\n\n- first item\n- second item\n\n```python\n",
    "Here is a short answer.\n\n- first item\n- second item\n\n```python\nprint(1)\n```\n",
    "Here is a short answer.\n\n- first item\n- second item\n\n```python\nprint(1)\n```\n\n"
    "And a final paragraph that is long enough to wrap",
]

passed = failed = 0


def check(label, ok, detail=""):
    global passed, failed
    print(("ok  " if ok else "FAIL"), label, detail)
    passed += ok
    failed += not ok


async def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="harness-scroll-"))
    try:
        app = HarnessApp(project=str(root))
        async with app.run_test(size=(70, 14)) as pilot:
            await pilot.pause()
            app.query_one("#prompt").focus()
            await pilot.press(*"hello")
            await pilot.press("enter")
            await pilot.pause(0.3)

            # --- while streaming, the view stays at the bottom --------------
            gaps = []
            for chunk in CHUNKS:
                app._stream_text = chunk
                result = app._flush_stream()
                if asyncio.iscoroutine(result):        # older code was sync
                    await result
                await pilot.pause(0.1)
                chat = app.query_one("#chat")
                gaps.append(chat.max_scroll_y - chat.scroll_offset.y)
            check(
                "the view stays at the bottom while streaming",
                all(gap <= 1 for gap in gaps),
                f"(gaps: {gaps})",
            )

            # --- scrolling up stops the following ---------------------------
            chat = app.query_one("#chat")
            chat.scroll_to(y=0, animate=False)
            await pilot.pause(0.2)
            check("scrolling up stops the follow", getattr(app, "_follow", True) is False)

            before = chat.scroll_offset.y
            app._stream_text += "\n\none more line of text"
            result = app._flush_stream()
            if asyncio.iscoroutine(result):
                await result
            await pilot.pause(0.1)
            check(
                "the view stays where the user put it",
                chat.scroll_offset.y == before,
                f"({before} -> {chat.scroll_offset.y})",
            )

            # --- scrolling back down starts it again -------------------------
            chat.scroll_end(animate=False)
            await pilot.pause(0.2)
            check("scrolling back down follows again", getattr(app, "_follow", True) is True)

            await app.action_quit()
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
