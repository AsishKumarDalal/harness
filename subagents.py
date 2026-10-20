"""subagents.py — child agents running in threads (Hermes' delegate_task).

A child = a fresh Conversation + the same loop shape as main.agent(), running
QUIETLY in a thread. Rules (from Hermes):
  - the child knows NOTHING except goal + context (goal is its first user turn)
  - it never sees the 'delegate' tool (no recursion)
  - the parent receives ONLY a trimmed summary + the child's session id
  - its full transcript lands in sessions.db (own session row), so nothing is lost
"""

import concurrent.futures
import threading
import time

import config
import llm
import sessions
import tools
from context import maybe_compact
from llm import chat
from messages import Conversation, default_system_prompt

_print_lock = threading.Lock()


def _child_prompt(context, depth=1):
    """Hermes' focused child prompt. The GOAL is NOT here — it's the first user turn."""
    parts = [default_system_prompt()]
    if context and context.strip():
        parts.append("CONTEXT:\n" + context)
    parts.append(
        "Complete this task using your tools. When finished, answer with a TIGHT summary: "
        "what you did, what you found, files changed, issues. Bullets over paragraphs. "
        "Do NOT replay your whole process — the parent only receives this summary, "
        "and long summaries crowd out its context window."
    )
    if depth >= config.MAX_SPAWN_DEPTH:
        parts.append("NOTE: you are at the maximum nesting depth; you cannot delegate further.")
    else:
        parts.append("You are an orchestrator: you have the 'delegate' tool and may split "
                     "the task yourself while depth remains.")
    return "\n\n".join(parts)


def _child_schema(allowed=None, depth=1):
    """Parent's schema minus delegate (unless the child may orchestrate)."""
    blocked = set() if depth < config.MAX_SPAWN_DEPTH else {"delegate"}
    return [t for t in tools.SCHEMA
            if t["function"]["name"] not in blocked
            and (allowed is None or t["function"]["name"] in allowed)]


def _trim(summary, sid, cap):
    """Hermes' summary budget: head 75% + tail 25% + pointer instead of spill files."""
    if len(summary) <= cap:
        return summary
    head, tail = int(cap * 0.75), int(cap * 0.25)
    return (summary[:head]
            + "\n\n[... middle omitted — trimmed to protect the parent's context ...]\n\n"
            + summary[-tail:]
            + f"\n[full transcript in session {sid} — recover with session_search]")


def run_tool_safe(call):
    """run_tool that can't crash the child (registry gaps etc.)."""
    try:
        return tools.run_tool(call)
    except Exception as e:
        return f"Error: {e}"


def run_child(task, index, n) -> dict:
    """Run ONE child agent to completion, in this thread. Returns its result entry."""
    goal = (task.get("goal") or "").strip()
    context = task.get("context")
    allowed = task.get("tools")            # optional list of tool names
    depth = int(task.get("depth", 1))
    prompt = _child_prompt(context, depth)

    tools.allow_tools([t["function"]["name"] for t in _child_schema(allowed, depth)])
    tools.set_quiet(True)                  # children never print streaming/tool lines

    sid = sessions.new_session(title=goal[:60] or None, system_prompt=prompt,
                               model=config.MODEL, cwd=str(config.START_DIR),
                               parent_session_id=sessions.current_id())
    convo = Conversation(prompt, sid)
    convo.add_user(goal)                   # goal = first user turn (Hermes contract)
    schema = _child_schema(allowed, depth)

    status, summary, start, done = "completed", "", time.time(), False
    try:
        for _ in range(config.SUBAGENT_MAX_TURNS):
            convo.history[:] = maybe_compact(convo.history)
            convo.sync()
            reply = chat(convo.history, tools=schema)
            convo.add_assistant(reply)
            if reply.tool_calls:
                for t in reply.tool_calls:
                    convo.add_tool(t.id, run_tool_safe(t))
            else:
                summary, done = (reply.content or "").strip(), True
                break
        if not done:
            summary = f"(stopped after {config.SUBAGENT_MAX_TURNS} tool turns)"
    except Exception as e:
        status, summary = "failed", f"error: {e}"
    finally:
        tools.allow_tools(None)            # reset THIS thread's restriction
        tools.set_quiet(False)
        sessions.end_session(sid, reason=status)

    duration = round(time.time() - start, 1)
    with _print_lock:
        mark = "✓" if status == "completed" else "✗"
        print(f"  {mark} [{index + 1}/{n}] {goal[:50]}  ({duration}s)")

    summary = _trim(summary, sid, config.SUBAGENT_SUMMARY_CHARS) or "(no summary returned)"
    return {"session_id": sid, "status": status,
            "duration_seconds": duration, "goal": goal, "summary": summary}


def run_batch(tasks) -> str:
    """Fan out one delegate call to N parallel children; ONE result back."""
    if not isinstance(tasks, list) or not tasks:
        return "error: delegate needs tasks: [{goal, context}]"
    if not all(isinstance(t, dict) and (t.get("goal") or "").strip() for t in tasks):
        return "error: each task needs a non-empty goal"

    n_max = config.MAX_SUBAGENTS
    dropped = tasks[n_max:]
    tasks = tasks[:n_max]
    llm.client()                           # warm the client BEFORE threads race on it

    with concurrent.futures.ThreadPoolExecutor(max_workers=n_max) as pool:
        entries = list(pool.map(run_child, tasks, range(len(tasks)), [len(tasks)] * len(tasks)))

    header = f"[{len(tasks)} subagent(s) finished"
    if dropped:                            # say WHICH tasks were dropped, so the
        goals = [str(t.get("goal") or "?")[:80]   # parent can re-delegate just those
                 for t in dropped]
        header += (f", {len(dropped)} DROPPED (parallel limit {n_max}) — these are "
                   f"STILL UNDONE, delegate them in a follow-up call: "
                   + " | ".join(goals))
    header += "]\n"

    lines = [header]
    for e in entries:
        lines.append("── subagent ─────────────────────────")
        lines.append(f"goal:    {e['goal']}")
        lines.append(f"status:  {e['status']} ({e['duration_seconds']}s)")
        lines.append(f"session: {e['session_id']}   (full transcript — session_search knows it)")
        lines.append("summary:")
        lines.append(e["summary"])
    return "\n".join(lines)