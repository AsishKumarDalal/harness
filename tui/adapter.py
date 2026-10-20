"""tui/adapter.py — drive the harness core from a Textual app.

The harness (llm / tools / safety / sessions / context) is used **as is**.
This module only:

  * runs the agent loop in a worker thread, so the UI never blocks
  * turns harness activity into the small events in `tui.events`
  * asks the UI for approval before a tool that needs one
  * snapshots files so edits can be shown as a diff

Harness changes required for this: exactly one — `llm.chat()` grew an
optional `stop` hook so a generation can be interrupted (Esc). Everything
else here is plain reuse of the existing modules.
"""

from __future__ import annotations

import asyncio
import difflib
import json
import threading
from pathlib import Path
from typing import Any, AsyncIterator, Iterable

import config
import llm
import safety
import sessions
import tools
from context import maybe_compact
from main import read_AGENT
from messages import Conversation, default_system_prompt
from tools import SCHEMA, run_tool

from .events import (
    ApprovalNeeded,
    Thinking,
    Token,
    ToolCall,
    ToolDiff,
    ToolResult,
    TurnDone,
    TurnEnd,
    TurnError,
)

DENIED = "Error: user denied this action."

# Tools whose effect is a file edit — we snapshot them to build a diff.
FILE_TOOLS = {"write_file", "edit_file"}

# How long the UI may take to answer an approval prompt before we give up.
APPROVAL_TIMEOUT = 300.0


class HarnessAdapter:
    """A thin, UI-shaped view of the harness."""

    def __init__(
        self,
        model: str | None = None,
        project: str | Path | None = None,
        max_turns: int = 20,
    ) -> None:
        if project:
            config.set_project_dir(project)
        self.model = model or config.MODEL
        self.max_turns = max_turns
        self.convo: Conversation | None = None
        self.session_id: str | None = None
        self._cancel = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: asyncio.Queue | None = None
        self._approvals: dict[str, tuple[threading.Event, list[str]]] = {}

    # ------------------------------------------------------------------
    # sessions
    # ------------------------------------------------------------------

    def new_session(self, title: str | None = None) -> str:
        """Start a fresh conversation (persisted in the notebook).

        The project's own AGENT.md is the system prompt when it has one —
        read from the PROJECT folder, never from the harness' own folder.
        """
        system = self.agent_md() or default_system_prompt()
        self.session_id = sessions.new_session(
            title, system, self.model, str(config.START_DIR)
        )
        self.convo = Conversation(system, self.session_id)
        return self.session_id

    def agent_md(self) -> str:
        """The project folder's AGENT.md (empty when it has none).

        Read-only, and always from `config.START_DIR` — the folder the agent
        works on. The harness' own AGENT.md is never used. The CLI's own
        loader is reused so both front-ends agree on the rule.
        """
        return read_AGENT() or ""

    def agent_md_name(self) -> str:
        """'AGENT.md' when the project has one, else '' (for the status bar)."""
        return "AGENT.md" if self.agent_md() else ""

    def resume(self, session_id: str) -> list[dict]:
        """Load a stored session and return its messages."""
        row = sessions.find_session(session_id)
        if not row:
            raise ValueError(f"no session matching '{session_id}'")
        history = sessions.load_messages(row["id"])
        system = default_system_prompt()
        if history and history[0].get("role") == "system":
            system = history[0].get("content") or system
        self.session_id = row["id"]
        self.convo = Conversation(system, row["id"])
        self.convo.history = history
        return history

    def list_sessions(self, limit: int = 20) -> list[dict]:
        """Stored sessions, newest first."""
        return sessions.list_sessions(limit)

    def session_label(self) -> str:
        """A friendly name for the current session: its title, else its id."""
        if not self.session_id:
            return ""
        row = sessions.find_session(self.session_id) or {}
        title = (row.get("title") or "").strip()
        return title or self.session_id

    # ------------------------------------------------------------------
    # the turn
    # ------------------------------------------------------------------

    async def send(self, text: str) -> AsyncIterator[Any]:
        """Send a user message; yields events until the turn ends.

        The blocking agent loop runs in a thread; events are handed back
        through an asyncio queue.
        """
        if self.convo is None:
            self.new_session()
        assert self.convo is not None

        self._loop = asyncio.get_running_loop()
        self._queue: asyncio.Queue = asyncio.Queue()
        self._cancel.clear()

        convo = self.convo
        convo.add_user(text)
        sessions.auto_title(convo.session_id, text.strip().splitlines()[0][:60])

        task = asyncio.create_task(asyncio.to_thread(self._run_turn, convo))
        try:
            while True:
                event = await self._queue.get()
                yield event
                if isinstance(event, TurnEnd):
                    return
        finally:
            if not task.done():
                self.cancel()
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass

    def cancel(self) -> None:
        """Interrupt the running generation (Esc)."""
        self._cancel.set()
        self._deny_pending_approvals()

    # ------------------------------------------------------------------
    # approvals
    # ------------------------------------------------------------------

    def resolve_approval(self, call_id: str, decision: str) -> None:
        """Answer an approval prompt: 'once' | 'always' | 'deny'."""
        entry = self._approvals.get(call_id)
        if entry is None:
            return
        event, result = entry
        result.append(decision)
        event.set()

    def _deny_pending_approvals(self) -> None:
        for event, result in self._approvals.values():
            if not result:
                result.append("deny")
            event.set()

    def _ask_approval(self, call_id: str, name: str, args: dict) -> str:
        """Block the worker thread until the UI answers (or times out)."""
        event = threading.Event()
        result: list[str] = []
        self._approvals[call_id] = (event, result)
        self._emit(ApprovalNeeded(call_id=call_id, name=name, args=args,
                                  summary=summarize_call(name, args)))
        event.wait(APPROVAL_TIMEOUT)
        self._approvals.pop(call_id, None)
        if self._cancel.is_set():
            return "deny"
        return result[0] if result else "deny"

    # ------------------------------------------------------------------
    # the blocking loop (runs in a thread)
    # ------------------------------------------------------------------

    def _run_turn(self, convo: Conversation) -> None:
        tools.set_quiet(True)          # the TUI renders tool calls itself
        try:
            for _ in range(self.max_turns):
                if self._cancel.is_set():
                    break

                new_history = maybe_compact(convo.history)
                if new_history is not convo.history:
                    convo.history[:] = new_history
                    convo.sync()

                reply = llm.chat(
                    convo.history,
                    tools=SCHEMA,
                    model=self.model,
                    on_token=lambda piece: self._emit(Token(text=piece)),
                    on_thinking=lambda piece: self._emit(Thinking(text=piece)),
                    stop=self._cancel.is_set,
                )
                if self._cancel.is_set():
                    # keep the partial answer so the history stays valid
                    convo.add_assistant(reply)
                    break

                convo.add_assistant(reply)
                if not reply.tool_calls:
                    self._emit(TurnDone(content=reply.content or ""))
                    break

                results: dict[str, str] = {}
                for call in reply.tool_calls:
                    results[call.id] = self._run_one_tool(call)

                for call in reply.tool_calls:          # results go back in CALL order
                    convo.add_tool(call.id, results[call.id])
            else:
                self._emit(TurnError(message=f"stopped after {self.max_turns} tool turns"))
        except Exception as exc:                       # never kill the UI thread
            self._emit(TurnError(message=str(exc)))
        finally:
            tools.set_quiet(False)
            self._emit(TurnEnd(cancelled=self._cancel.is_set()))

    def _run_one_tool(self, call) -> str:
        """Run one tool call: policy check -> approval -> execute -> result."""
        name = call.function.name
        try:
            args = json.loads(call.function.arguments or "{}")
        except Exception:
            args = {}
        if not isinstance(args, dict):
            args = {}

        self._emit(ToolCall(call_id=call.id, name=name, args=args))

        before = self._snapshot(args.get("path", "")) if name in FILE_TOOLS else None

        decision = "once"
        if needs_approval(name, args):
            decision = self._ask_approval(call.id, name, args)
            if decision == "deny":
                self._emit(ToolResult(call_id=call.id, name=name,
                                      output=DENIED, status="denied"))
                return DENIED
            if decision == "always":
                remember_rule(name, args)

        output = run_tool(call)
        status = "done"
        if output.startswith("Error"):
            status = "failed"
        self._emit(ToolResult(call_id=call.id, name=name, output=output, status=status))

        if name in FILE_TOOLS:
            after = self._snapshot(args.get("path", ""))
            diff = make_diff(before, after, str(args.get("path", "")))
            if diff:
                self._emit(ToolDiff(call_id=call.id, path=str(args.get("path", "")),
                                    diff=diff))
        return output

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _snapshot(self, path: str) -> str | None:
        """File content before/after a write (None if unreadable)."""
        if not path:
            return None
        try:
            target = (config.START_DIR / path).resolve()
            target.relative_to(config.START_DIR.resolve())
            return target.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return None

    def _emit(self, event) -> None:
        """Push an event to the UI thread (called from the worker thread)."""
        loop, queue = self._loop, self._queue
        if loop is None or queue is None:
            return
        try:
            loop.call_soon_threadsafe(queue.put_nowait, event)
        except RuntimeError:
            pass                                 # loop already closed


# ----------------------------------------------------------------------
# policy helpers (read-only use of the harness' safety module)
# ----------------------------------------------------------------------

def needs_approval(name: str, args: dict) -> bool:
    """Would the harness ask a human before running this tool?"""
    if safety.blocked_tool_message(name, args):
        return False                            # refused outright, no point asking
    if safety.mode() == "auto":
        return False                            # auto mode never prompts
    if name in safety.FREE_TOOLS:
        return False
    if name == "run_command":
        command = str(args.get("command", ""))
        if safety.is_readonly(command):
            return False
        if _command_allowed(command):
            return False
    if f"tool:{name}" in safety.list_rules():
        return False
    return True


def _command_allowed(command: str) -> bool:
    """Is the command covered by a saved 'always' rule?"""
    allowed = getattr(safety, "_command_allowed", None)
    if allowed is not None:
        return bool(allowed(command))
    return False


def remember_rule(name: str, args: dict) -> None:
    """Persist an 'always' answer (same shape the harness uses)."""
    if name == "run_command":
        for part in safety.split_compounds(str(args.get("command", ""))):
            if part and not safety.is_readonly_part(part):
                safety.add_rule(f"bash:{part}")
    else:
        safety.add_rule(f"tool:{name}")


def summarize_call(name: str, args: dict) -> str:
    """One-line human summary of a tool call (shown in the approval prompt)."""
    if name == "run_command":
        return str(args.get("command", ""))[:300]
    if name in FILE_TOOLS:
        return str(args.get("path", ""))
    if name == "web_fetch":
        return str(args.get("url", ""))[:300]
    if name == "web_search":
        return str(args.get("query", ""))[:300]
    if name == "delegate":
        tasks = args.get("tasks") or []
        goals = [str(t.get("goal", ""))[:60] for t in tasks if isinstance(t, dict)]
        return "; ".join(goals)[:300]
    return ", ".join(f"{k}={str(v)[:40]}" for k, v in list(args.items())[:3])[:300]


def make_diff(before: str | None, after: str | None, path: str) -> str:
    """Unified diff between two file contents (empty when identical)."""
    old = (before or "").splitlines(keepends=True)
    new = (after or "").splitlines(keepends=True)
    if before is None:
        old = []
    if after is None:
        new = []
    diff = difflib.unified_diff(old, new, fromfile=f"a/{path}", tofile=f"b/{path}", n=3)
    return "".join(diff)
