"""tui/widgets/chat_area.py — the scrollable history, with a sticky bottom.

The view follows the stream while it is parked at the last line. Scroll up
to read something and it stops following; scroll back down and it starts
again. That is what stops the screen from jumping around while a long
answer streams in.

The sticking is done with Textual's own *anchoring*: an anchored widget is
pinned to the bottom by the compositor while the content grows, in the same
frame the content is laid out. A manual `scroll_end()` is not enough - it
is deferred to the next refresh, so the new text is painted first and the
view catches up a frame later. That one-frame lag is the bobbing.
"""

from __future__ import annotations

from textual.containers import VerticalScroll
from textual.geometry import Offset
from textual.message import Message


class ChatArea(VerticalScroll):
    """The message history."""

    class FollowChanged(Message):
        """The view moved: is it still parked at the bottom?"""

        def __init__(self, follow: bool) -> None:
            super().__init__()
            self.follow = follow

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._last_follow: bool | None = None

    @property
    def at_bottom(self) -> bool:
        """Is the last line of the history visible?"""
        return self.scroll_offset.y >= self.max_scroll_y - 1

    @property
    def scroll_offset(self) -> Offset:
        """The scroll offset, never above the top of the content.

        The anchor works out "bottom of the content - height of the viewport".
        While the content is shorter than the viewport that is negative, and
        a negative offset pushes the text down and clips its last line.
        """
        offset = super().scroll_offset
        return offset if offset.y >= 0 else Offset(offset.x, 0)

    @property
    def following(self) -> bool:
        """Is the view pinned to the bottom (following the stream)?"""
        return self.is_anchored and not self._anchor_released

    def follow(self) -> None:
        """Pin the view to the bottom.

        From here on the compositor keeps the last line in place while new
        content arrives, so a streaming answer never moves the text that is
        already on screen.
        """
        if not self.following:
            self.anchor()

    def watch_scroll_y(self, old_value: float, new_value: float) -> None:
        """Tell the app when the user moves the view."""
        super().watch_scroll_y(old_value, new_value)
        if new_value < 0:
            # The anchor works out "bottom - viewport", which is negative when
            # the content is shorter than the viewport. That would push the
            # text down and clip its last line, so it is clamped back to 0.
            self.scroll_y = 0
            return
        at_bottom = self.at_bottom
        if at_bottom != self._last_follow:
            self._last_follow = at_bottom
            self.post_message(self.FollowChanged(at_bottom))
