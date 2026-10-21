"""Offline probe: the streamed answer must render like a finished one.

Run:  .venv/bin/python test/test_tui_stream.py   (from project root)

Two things are checked here:

1. the answer is *appended* while it streams, so the rendering has to be
   the same as a single Markdown block with the whole text (paragraphs,
   lists, a code fence, a table)
2. a flush must not get slower the longer the answer gets - that is what
   made the screen crawl behind the stream and jump in big steps
"""

import asyncio
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from textual.app import App, ComposeResult  # noqa: E402
from textual.containers import VerticalScroll  # noqa: E402
from textual.widgets import Markdown  # noqa: E402

from tui.app import HarnessApp  # noqa: E402
from tui.widgets.chat_area import ChatArea  # noqa: E402

DOC = """First paragraph with a few words in it.

Second paragraph, a bit longer, so it wraps over more than one line in a
narrow window and the text keeps folding instead of being cut.

- item one
- item two
- item three

```python
def hello(name):
    return f"hi {name}"
```

| tool | use |
|------|-----|
| read | look at a file |

And a closing paragraph.
"""

passed = failed = 0


def check(label, ok, detail=""):
    global passed, failed
    print(("ok  " if ok else "FAIL"), label, detail)
    passed += ok
    failed += not ok


class Reference(App):
    """The same document, rendered in one go."""

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield Markdown(DOC)


def screen_lines(app) -> list[str]:
    """The visible text of the app, empty lines dropped."""
    out = []
    for strip in app.screen._compositor.render_strips():
        text = strip.text.rstrip()
        if text.strip():
            out.append(text)
    return out


#: what else is in the chat area: the welcome text and the session note
NOISE = (
    "harness — opencode-style",
    "Type a request",
    "/help for commands",
    "ctrl+p",
    "session 2",
)


def chat_lines(app, chat) -> list[str]:
    """Only the answer: no welcome text, no session note."""
    strips = app.screen._compositor.render_strips()
    top = chat.region.y
    out = []
    for strip in strips[top:top + chat.region.height]:
        text = strip.text.rstrip()
        if not text.strip():
            continue
        if any(noise in text for noise in NOISE):
            continue
        out.append(text)
    return out


def words(lines: list[str]) -> list[str]:
    """The words of some lines - the wrapping and the box drawing do not
    matter (the chat is narrower than the reference, so a table is drawn
    with different borders)."""
    out = []
    for word in " ".join(" ".join(lines).split()).split():
        letters = sum(1 for char in word if char.isalnum())
        if letters * 2 >= len(word):      # a word, not a border
            out.append(word)
    return out


async def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="harness-stream-"))
    try:
        # --- the reference: one Markdown with the whole text ---------------
        reference = Reference()
        async with reference.run_test(size=(60, 40)) as pilot:
            await pilot.pause()
            expected = screen_lines(reference)
            await reference.action_quit()

        # --- the same text, streamed through the TUI ------------------------
        app = HarnessApp(project=str(root))
        async with app.run_test(size=(60, 40)) as pilot:
            await pilot.pause()
            app.query_one("#prompt").focus()
            chat = app.query_one("#chat", ChatArea)

            costs = []
            for i in range(0, len(DOC), 13):
                app._stream_text = DOC[: i + 13]
                start = time.monotonic()
                await app._flush_stream()
                costs.append(time.monotonic() - start)
                await pilot.pause(0.005)

            streamed = chat_lines(app, chat)
            got = words(streamed)
            want = words(expected)
            check(
                "the streamed answer reads like the finished one",
                got == want,
                f"({len(expected)} lines in the document)",
            )
            if got != want:
                import difflib
                for line in list(difflib.unified_diff(want, got, "want", "got", lineterm=""))[:40]:
                    print(line)
            check(
                "the code fence is not shown as raw text",
                "```python" not in " ".join(streamed),
            )
            check(
                "the list is a list",
                any("item one" in ln for ln in streamed),
            )

            first = sum(costs[:5]) / 5
            last = sum(costs[-5:]) / 5
            check(
                "a flush does not get slower as the answer grows",
                last < max(first * 3, 0.02),
                f"(first {first * 1000:.1f} ms, last {last * 1000:.1f} ms)",
            )
            await app.action_quit()

        # --- the same, with a long answer ------------------------------------
        app = HarnessApp(project=str(root))
        async with app.run_test(size=(70, 24)) as pilot:
            await pilot.pause()
            app.query_one("#prompt").focus()
            chat = app.query_one("#chat", ChatArea)

            long_doc = "".join(
                f"Paragraph {n}: " + "word " * 30 + "\n\n" for n in range(1, 120)
            )
            costs = []
            for i in range(0, len(long_doc), 200):
                app._stream_text = long_doc[: i + 200]
                start = time.monotonic()
                await app._flush_stream()
                costs.append(time.monotonic() - start)
                await pilot.pause(0.001)

            first = sum(costs[:5]) / 5
            last = sum(costs[-5:]) / 5
            check(
                "a long answer does not make the flush slower",
                last < max(first * 3, 0.02),
                f"(first {first * 1000:.1f} ms, last {last * 1000:.1f} ms, "
                f"{len(long_doc.splitlines())} lines)",
            )
            await app.action_quit()
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
