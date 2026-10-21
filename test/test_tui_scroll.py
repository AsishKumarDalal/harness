"""Offline probe: the chat must follow the stream and never jump around.

Run:  .venv/bin/python test/test_tui_scroll.py   (from project root)

Regression test for the jumping view. The old code scrolled with
`scroll_end(animate=False)`, which is deferred to the *next* refresh: the
new text was painted first and the view caught up a frame later, so every
flush showed the view a line or two above the end - a continuous bob while
the answer streamed in.

The fix is Textual's anchoring: the compositor pins the view to the bottom
in the same frame the content is laid out. So the test watches the chat
while it is *painted* (render_line) and asks: was this line painted with
the view at the bottom?
"""

import asyncio
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tui.app import HarnessApp  # noqa: E402
from tui.widgets.chat_area import ChatArea  # noqa: E402

PARAGRAPH = "".join(
    f"Paragraph {n}: " + "word " * 30 + "\n\n" for n in range(1, 8)
)
CHUNKS = [PARAGRAPH[i:i + 48] for i in range(0, len(PARAGRAPH), 48)]

passed = failed = 0


def check(label, ok, detail=""):
    global passed, failed
    print(("ok  " if ok else "FAIL"), label, detail)
    passed += ok
    failed += not ok


async def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="harness-scroll-"))
    painted: list[tuple[float, int]] = []
    original = ChatArea.render_line

    def render_line(self, y):
        painted.append((self.scroll_offset.y, self.max_scroll_y))
        return original(self, y)

    ChatArea.render_line = render_line
    try:
        app = HarnessApp(project=str(root))
        async with app.run_test(size=(70, 20)) as pilot:
            await pilot.pause()
            app.query_one("#prompt").focus()
            await pilot.press(*"hello")
            await pilot.press("enter")
            await pilot.pause(0.3)
            chat = app.query_one("#chat", ChatArea)

            # --- while streaming, the view is painted at the bottom --------
            text = ""
            for chunk in CHUNKS:
                text += chunk
                app._stream_text = text
                await app._flush_stream()
                await pilot.pause(0.004)     # a frame may be painted here

            behind = [maxv - y for y, maxv in painted if maxv > 0 and maxv - y > 1]
            check(
                "every painted frame is at the bottom while streaming",
                not behind,
                f"(painted {len(painted)} lines, {len(behind)} above the end)",
            )
            check(
                "the view sits exactly at the bottom",
                chat.max_scroll_y - chat.scroll_offset.y <= 1,
                f"(gap {chat.max_scroll_y - chat.scroll_offset.y})",
            )
            check(
                "the view never scrolls above the top",
                chat.scroll_offset.y >= 0,
                f"(y {chat.scroll_offset.y})",
            )

            # --- scrolling up stops the following ---------------------------
            chat.scroll_to(y=0, animate=False)
            await pilot.pause(0.2)
            check("scrolling up stops the follow", chat.following is False)

            before = chat.scroll_offset.y
            app._stream_text += "\n\none more line of text"
            await app._flush_stream()
            await pilot.pause(0.1)
            check(
                "the view stays where the user put it",
                chat.scroll_offset.y == before,
                f"({before} -> {chat.scroll_offset.y})",
            )

            # --- scrolling back down starts it again -------------------------
            chat.scroll_end(animate=False)
            await pilot.pause(0.2)
            check("scrolling back down follows again", chat.following is True)

            # --- a new turn starts at the bottom again ------------------------
            chat.scroll_to(y=0, animate=False)
            await pilot.pause(0.2)
            check("scrolling up stops the follow again", chat.following is False)
            app._busy = False               # the first turn is still running
            app._send("a new question")
            await pilot.pause(0.2)
            check("a new turn pins the view to the bottom", chat.following is True)
            check(
                "and it is at the bottom",
                chat.max_scroll_y - chat.scroll_offset.y <= 1,
                f"(gap {chat.max_scroll_y - chat.scroll_offset.y})",
            )

            await app.action_quit()
    finally:
        ChatArea.render_line = original
        shutil.rmtree(root, ignore_errors=True)

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
