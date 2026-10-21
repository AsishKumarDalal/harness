"""Offline layout probe: long content must wrap, never be cut at the right edge.

Run:  .venv/bin/python test/test_tui_layout.py   (from project root)

Regression test for the "tokens get cut at the right" bug: the message
blocks were sized with `width: auto`, so a long line was laid out on one
line and clipped by the chat area instead of wrapping.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from textual.widgets import Markdown, Static  # noqa: E402

from tui.app import HarnessApp  # noqa: E402
from tui.widgets.diff_view import DiffView  # noqa: E402

WIDTH = 80
LONG_TEXT = "the model wrote a long sentence that has to wrap somewhere. " * 20
LONG_TOKEN = "x" * 300

passed = failed = 0


def check(label, ok, detail=""):
    global passed, failed
    print(("ok  " if ok else "FAIL"), label, detail)
    passed += ok
    failed += not ok


async def main() -> int:
    app = HarnessApp(project="/tmp/opencode/harness-tui-layout-test")
    async with app.run_test(size=(WIDTH, 30)) as pilot:
        await pilot.pause()
        chat = app.query_one("#chat")
        room = chat.content_size.width

        # 1. a long user message
        user = Static(LONG_TEXT, classes="user-message", markup=False)
        chat.mount(user)
        await pilot.pause(0.2)
        check("user message does not overflow", user.size.width <= room,
              f"({user.size.width} <= {room})")
        check("user message wrapped", user.size.height > 1,
              f"({user.size.height} lines)")

        # 2. a long assistant answer (markdown)
        answer = Markdown(LONG_TEXT, classes="assistant-message")
        chat.mount(answer)
        await pilot.pause(0.2)
        check("assistant answer does not overflow", answer.size.width <= room,
              f"({answer.size.width} <= {room})")
        check("assistant answer wrapped", answer.size.height > 1,
              f"({answer.size.height} lines)")

        # 3. a single very long token must fold onto several lines
        diff = DiffView("+" + LONG_TOKEN + "\n", "f")
        chat.mount(diff)
        await pilot.pause(0.2)
        check("long token does not overflow", diff.size.width <= room,
              f"({diff.size.width} <= {room})")
        check("long token folded", diff.size.height > 1,
              f"({diff.size.height} lines)")

        # 4. nothing is dropped: the block is tall enough to hold every line
        content_width = answer.size.width - 2          # minus the padding
        expected = -(-len(LONG_TEXT) // content_width)  # ceil
        check("answer holds every line", answer.size.height >= expected - 1,
              f"({answer.size.height} lines, need ~{expected})")

        # 5. and the text really reaches the screen
        chat.scroll_to_widget(answer, animate=False)
        await pilot.pause(0.2)
        on_screen = " ".join(
            " ".join(strip.text for strip in app.screen._compositor.render_strips()).split()
        )
        check("answer is on screen", "wrap somewhere" in on_screen)

        await app.action_quit()

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
