"""tui — a Textual front-end for The Harness.

The harness core (llm / tools / safety / sessions / context) is used as-is.
Everything TUI-specific lives in this package and talks to the core through
` tui.adapter.HarnessAdapter `.
"""

from .adapter import HarnessAdapter

__all__ = ["HarnessAdapter"]
