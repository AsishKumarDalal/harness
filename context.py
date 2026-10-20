"""context.py — keeps the conversation small enough to fit the model.

The model has NO memory. Whatever WE send it IS its memory.
So we are allowed to rewrite old messages. Two levels, cheapest first:

  Level 1 (PRUNE, at 45% of window):
      Replace OLD tool outputs with one-line stubs. No LLM needed.
      Originals are archived in the notebook (active=0) by sync() — nothing
      is lost; session_search recovers them.

  Level 2 (COMPACT, at 75% of window):
      Ask the model to summarize the OLD middle messages into a short note.
      First rows + newest rows stay exactly as they are.
      If the summary comes back empty/garbage, build a dumb note ourselves.
      We never delete messages without a replacement.
"""

import re

import config
from config import (CONTEXT_BUDGET, KEEP_HEAD, KEEP_TAIL, PRUNE_AT, COMPACT_AT,
                    COMPACT_TO, SUMMARY_MODEL, MODEL)
from llm import chat

RECENT_TURNS_TO_KEEP = 6                 # newest tool results stay untouched
PRUNE_MIN_CHARS = 200                    # don't stub tiny results (saves nothing)

SECRET = re.compile(r"sk-[A-Za-z0-9_-]{8,}")   # never copy API keys into notes


def redact(text) -> str:
    return SECRET.sub("[REDACTED]", str(text or ""))


# ------------------------------------------------------------------
# STEP 1 — guess the token count (no real tokenizer needed)
# ------------------------------------------------------------------

def tokens(text) -> int:
    """Rule of thumb: 4 characters = 1 token. Accurate enough for an alarm."""
    n = len(str(text or "")) // 4
    return n if n > 0 else 1


def history_tokens(history: list) -> int:
    """Rough token count of the whole messages list."""
    total = 0
    for m in history:
        total = total + tokens(m.get("content"))
        total = total + tokens(m.get("tool_calls"))
        total = total + 8                    # role/id/structure overhead
    return total


# ------------------------------------------------------------------
# STEP 2 — LEVEL 1: stub old tool outputs (free, no LLM at all)
# ------------------------------------------------------------------

def prune_tool_results(history: list) -> list:
    """Walk newest -> oldest. Count tool turns. After the newest 6 turns,
    every big tool result becomes a one-line stub. Original is archived."""
    out = list(history)              # copy, so the caller's list is safe
    rounds_seen = 0                  # how many newer tool-turns we already passed
    for i in range(len(out) - 1, -1, -1):
        m = out[i]
        if m.get("role") == "assistant" and m.get("tool_calls"):
            rounds_seen = rounds_seen + 1
        elif m.get("role") == "tool":
            content = m.get("content") or ""
            if rounds_seen >= RECENT_TURNS_TO_KEEP and len(content) >= PRUNE_MIN_CHARS:
                # the original is preserved automatically: sync() archives the
                # row (active=0) into the notebook, so session_search finds it
                stub = f"[Old tool output cleared — {len(content)} chars, recover via session_search]"
                out[i] = {"role": "tool",
                          "tool_call_id": m.get("tool_call_id"),
                          "content": stub}
    return out


# ------------------------------------------------------------------
# STEP 3 — divide messages: head | middle | tail
# ------------------------------------------------------------------

def split_history(history: list):
    """head   = system + first KEEP_HEAD messages   (stays verbatim)
       middle = everything in between              (gets summarized)
       tail   = newest KEEP_TAIL messages          (stays verbatim)

    PROTOCOL RULE: the tail must not START with a 'tool' message — a tool
    result belongs to the assistant turn before it, and cutting between
    the two creates an invalid conversation. So we move that assistant
    turn down into the tail instead."""
    if len(history) <= 1 + KEEP_HEAD + KEEP_TAIL:
        return history[:1], [], []       # too small to compact anything
    head   = history[:1 + KEEP_HEAD]
    middle = list(history[1 + KEEP_HEAD:-KEEP_TAIL])
    tail   = list(history[-KEEP_TAIL:])
    while len(tail) > 0 and tail[0].get("role") == "tool" and len(middle) > 0:
        tail.insert(0, middle.pop())     # reunite the pair
    return head, middle, tail


# ------------------------------------------------------------------
# STEP 4 — LEVEL 2: summarize the middle (with fallbacks)
# ------------------------------------------------------------------

SUMMARY_INSTRUCTION = (
    "Compress part of a coding agent's conversation into a terse note with "
    "sections: ## Active Task / ## Done / ## Files & Findings / ## Errors / "
    "## Next Steps. Keep the user's goal exactly. Never include API keys or "
    "passwords — write [REDACTED] instead. Plain text, no preamble."
)


def summarize(middle: list) -> str:
    """Try cheap model first (if set), then main model, then a dumb fallback.
    An empty or refusal answer counts as failure — we just try the next."""
    lines = []
    for m in middle:
        text = m.get("content") or str(m.get("tool_calls") or "")
        lines.append(m.get("role") + ": " + text[:200])
    transcript = redact("\n".join(lines))[:8000]

    ask = [{"role": "system", "content": SUMMARY_INSTRUCTION},
           {"role": "user", "content": "Compress into the sectioned note:\n\n" + transcript}]
    routes = []
    if SUMMARY_MODEL:
        routes.append(SUMMARY_MODEL)
    routes.append(MODEL)
    for name in routes:
        try:
            reply = chat(ask, model=name)
            text = (reply.content or "").strip()
            bad = len(text) == 0 or text.lower().startswith(("sorry", "i can't", "i cannot"))
            if not bad:
                return text
            print("   [context] summary looked bad from", name, "- trying next route")
        except Exception as e:
            print("   [context] summary failed on", name, ":", e)

    fallback = []
    for m in middle:
        fallback.append("- " + m.get("role") + ": " + redact(str(m.get("content") or ""))[:120])
    return "\n".join(fallback)[:3000]


def compact_history(history: list) -> list:
    head, middle, tail = split_history(history)
    if len(middle) == 0:
        return history

    print(f"   [context] compacting {len(middle)} old messages...")
    summary = summarize(middle)

    note = {
        "role": "system",
        "content": ("[CONTEXT COMPACTION] Earlier turns were replaced by this note. "
                    "Treat it as background. Keep working normally with your tools.\n\n"
                    + summary),
    }
    new_history = head + [note] + tail

    has_user_in_tail = any(m.get("role") == "user" for m in tail)
    if not has_user_in_tail:
        for m in reversed(middle):
            if m.get("role") == "user":
                replay = {"role": "user",
                          "content": "[STILL IN PROGRESS — your request, restated:]\n\n"
                                     + str(m.get("content"))}
                new_history.insert(len(head) + 1, replay)
                break

    return prune_tool_results(new_history)


def maybe_compact(history: list) -> list:
    size = history_tokens(history)

    if size >= int(CONTEXT_BUDGET * COMPACT_AT):
        return compact_history(history)

    if size >= int(CONTEXT_BUDGET * PRUNE_AT):
        pruned = prune_tool_results(history)
        after = history_tokens(pruned)
        if after < size:
            print(f"   [context] pruned old tool outputs: ~{size} -> ~{after} tokens")
            return pruned
        return history

    return history