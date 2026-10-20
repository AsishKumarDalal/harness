"""tui/widgets/chat_area.py — the scrollable history, with a sticky bottom.

The view follows the stream while it is parked at the last line. Scroll up
to read something and it stops following; scroll back down and it starts
again. That is what stops the screen from jumping around while a long
answer streams in.
"""

from __future__ import annotations

from textual.containers import VerticalScroll
from textual.message import Message


class ChatArea(VerticalScroll):
    """The message history."""

    class FollowChanged(Message):
        """The view moved: is it still parked at the bottom?"""

        def __init__(self, follow: bool) -> None:
            super().__init__()
            self.follow = follow

    @property
    def at_bottom(self) -> bool:
        """Is the last line of the history visible?"""
        return self.scroll_offset.y >= self.max_scroll_y - 1

    def watch_scroll_y(self, old_value: float, new_value: float) -> None:
        """Tell the app when the user moves the view."""
        super().watch_scroll_y(old_value, new_value)
        self.post_message(self.FollowChanged(self.at_bottom))
