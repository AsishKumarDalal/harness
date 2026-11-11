"""benchmark/bench_context.py — does the two-tier context management work?

The harness rewrites its own history to fit the window (context.py):
  tier 1 (45%) prune  — stub OLD tool outputs, free, no LLM
  tier 2 (75%) compact — an LLM summarizes the middle

The rules that must not break (docs/README.md:44-52):
  * the newest 6 tool turns are never pruned
  * the tail never starts with a 'tool' message (protocol validity)
  * head and tail are kept verbatim
  * the user's request is replayed after a compaction
  * nothing is deleted — the originals stay in the notebook (active=0)

The token ESTIMATOR is also checked: context.tokens() assumes 4 chars =
1 token (context.py:40). How far off is that really? The live server
reports the true prompt_tokens, so bench_model.py measures the error
against the server; here we only check the estimator is self-consistent
and monotone.

Run:  .venv/bin/python benchmark/bench_context.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import Sandbox, Tally, banner, hr, record, save_report, use_sandbox  # noqa: E402

import config  # noqa: E402
import context as ctx  # noqa: E402
import fake_model  # noqa: E402


def make_history(turns=20, tool_chars=6000):
    """A history with big tool outputs, like a real busy session."""
    hist = [{"role": "system", "content": "system prompt"}]
    hist.append({"role": "user", "content": "the original request: fix the bug"})
    for i in range(turns):
        hist.append({"role": "assistant", "content": f"answer {i}",
                     "tool_calls": [{"id": f"c{i}", "type": "function",
                                     "function": {"name": "read_file",
                                                  "arguments": "{}"}}]})
        hist.append({"role": "tool", "tool_call_id": f"c{i}",
                     "content": "T" * tool_chars})
    return hist


def bench_estimator(tally: Tally):
    print("\n-- the token estimator --")
    for text in ("", "a", "abcd", "x" * 4000, "y" * 40000):
        t = ctx.tokens(text)
        print(f"  {len(text):>6} chars -> {t:>6} tokens "
              f"(ratio {len(text)/max(t,1):.2f} chars/token)")
    tally.check("tokens('') is 1, not 0", ctx.tokens(""), 1)
    tally.check("tokens of 4000 chars is 1000", ctx.tokens("x" * 4000), 1000)
    tally.check("the estimator is monotone", ctx.tokens("x" * 8000) > ctx.tokens("x" * 4000), True)


def bench_prune(tally: Tally):
    print("\n-- tier 1: prune --")
    hist = make_history(turns=20, tool_chars=6000)
    before = ctx.history_tokens(hist)
    pruned = ctx.prune_tool_results(hist)
    after = ctx.history_tokens(pruned)

    print(f"  tokens before: {before}   after: {after}   "
          f"saved: {round(100 * (before - after) / before, 1)}%")

    # the newest 6 tool turns must survive untouched
    newest = [m for m in pruned if m.get("role") == "tool"][-6:]
    kept = all(len(m.get("content", "")) == 6000 for m in newest)
    tally.check("the newest 6 tool results are NOT pruned", kept, True)

    # older ones must be stubbed
    older = [m for m in pruned if m.get("role") == "tool"][:-6]
    stubbed = all("Old tool output cleared" in (m.get("content") or "") for m in older)
    tally.check("older tool results ARE stubbed", stubbed, True)
    tally.check("the caller's list is not mutated",
                ctx.history_tokens(hist) == before, True)
    tally.check("pruning saves a meaningful amount", (before - after) / before > 0.5, True)
    return {"before": before, "after": after,
            "saved_pct": round(100 * (before - after) / before, 1)}


def bench_split(tally: Tally):
    print("\n-- the head/middle/tail split --")
    hist = make_history(turns=20)
    head, middle, tail = ctx.split_history(hist)
    print(f"  head={len(head)} middle={len(middle)} tail={len(tail)}")
    tally.check("head keeps the system prompt", head[0]["role"], "system")
    tally.check("head is protected", len(head), 1 + config.KEEP_HEAD)
    tally.check("tail is protected", len(tail) >= config.KEEP_TAIL, True)

    # the protocol rule: the tail must not start with a 'tool' message
    hist2 = make_history(turns=20)
    hist2.insert(-config.KEEP_TAIL, {"role": "tool", "tool_call_id": "x", "content": "T"})
    _, _, tail2 = ctx.split_history(hist2)
    tally.check("the tail never starts with a tool message",
                tail2[0].get("role") != "tool", True)

    # a history too small to compact is returned untouched
    small = hist[:5]
    h2, m2, t2 = ctx.split_history(small)
    tally.check("a small history is not split", (len(m2), len(t2)), (0, 0))
    return {"head": len(head), "middle": len(middle), "tail": len(tail)}


def bench_compact(tally: Tally):
    print("\n-- tier 2: compact (LLM summary) --")
    hist = make_history(turns=20)
    before = ctx.history_tokens(hist)

    # a scripted model stands in for the summary call
    script = fake_model.Script(turns=[[("c", "## Active Task\nfix the bug\n\n## Done\nnot yet")]])
    fake_model.install(script)

    compacted = ctx.compact_history(hist)
    after = ctx.history_tokens(compacted)

    print(f"  tokens before: {before}   after: {after}   "
          f"saved: {round(100 * (before - after) / before, 1)}%")

    roles = [m.get("role") for m in compacted]
    notes = [m for m in compacted if m.get("role") == "system"
             and "CONTEXT COMPACTION" in (m.get("content") or "")]
    tally.check("a compaction note was inserted", len(notes) >= 1, True)
    tally.check("the note carries the summary", "Active Task" in notes[0]["content"], True)
    # The invariant that matters: the user's request must survive the
    # compaction EITHER verbatim (it is in the protected head) OR as a
    # "[STILL IN PROGRESS]" replay (it was only in the summarized middle).
    request_text = "the original request: fix the bug"
    survives = any(request_text in (m.get("content") or "") for m in compacted)
    replayed = any("STILL IN PROGRESS" in (m.get("content") or "") for m in compacted)
    print(f"  request survives verbatim: {survives}   replayed: {replayed}")
    tally.check("the user's request survives the compaction", survives, True)
    tally.check("compaction saves tokens", after < before, True)
    tally.check("the head survives", compacted[0].get("role"), "system")
    tally.check("the protocol stays valid (no tool right after the note)",
                not (roles[roles.index("system") + 1] == "tool"
                     if roles.count("system") > 1 else False), True)
    return {"before": before, "after": after,
            "saved_pct": round(100 * (before - after) / before, 1),
            "request_survives": survives, "request_replayed": replayed}


def bench_replay(tally: Tally):
    """When the request is ONLY in the summarized middle, it must be replayed.

    The replay fires when the protected TAIL holds no user turn at all
    (context.py:164) — i.e. the last instruction the model saw may have
    been folded into the summary. So the history here ends with
    assistant/tool pairs and keeps a user turn only in the middle.
    """
    print("\n-- replay of a request that only lived in the middle --")
    hist = [{"role": "system", "content": "sys"}]
    hist.append({"role": "user", "content": "the very first request"})
    for i in range(10):
        hist.append({"role": "assistant", "content": f"answer {i}",
                     "tool_calls": [{"id": f"c{i}", "type": "function",
                                     "function": {"name": "read_file",
                                                  "arguments": "{}"}}]})
        hist.append({"role": "tool", "tool_call_id": f"c{i}", "content": "T" * 6000})
        if i == 3:
            hist.append({"role": "user", "content": "the request that matters"})

    head, middle, tail = ctx.split_history(hist)
    print(f"  head={len(head)} middle={len(middle)} tail={len(tail)}  "
          f"user in tail: {any(m.get('role') == 'user' for m in tail)}")

    script = fake_model.Script(turns=[[("c", "## Active Task\nsomething")]])
    fake_model.install(script)
    compacted = ctx.compact_history(hist)

    replayed = [m for m in compacted if "STILL IN PROGRESS" in (m.get("content") or "")]
    print(f"  replayed messages: {len(replayed)}")
    for m in replayed:
        print(f"     -> {m['content'][:90]!r}")
    tally.check("a request from the middle is replayed", len(replayed), 1)
    tally.check("the replay names the request",
                any("the request that matters" in m["content"] for m in replayed), True)
    return {"replayed": len(replayed)}


def bench_maybe(tally: Tally):
    print("\n-- the trigger thresholds --")
    # below 45%: nothing happens
    hist = [{"role": "system", "content": "s"},
            {"role": "user", "content": "u"},
            {"role": "assistant", "content": "a"},
            {"role": "tool", "tool_call_id": "c", "content": "x" * 1000}]
    out = ctx.maybe_compact(hist)
    tally.check("below the threshold nothing happens", out is hist, True)

    # the thresholds themselves
    tally.check("prune threshold is 45%", config.PRUNE_AT, 0.45)
    tally.check("compact threshold is 75%", config.COMPACT_AT, 0.75)
    budget = config.CONTEXT_BUDGET
    print(f"  budget={budget}  prune@{int(budget*config.PRUNE_AT)}  "
          f"compact@{int(budget*config.COMPACT_AT)}")
    return {"budget": budget}


def main():
    banner("BENCHMARK: context management — prune, compact, thresholds")
    with Sandbox("context") as sb:
        use_sandbox(sb, mode="auto")
        sb.write("main.py", "print(1)\n")

        tally = Tally()
        bench_estimator(tally)
        prune = bench_prune(tally)
        split = bench_split(tally)
        compact = bench_compact(tally)
        replay = bench_replay(tally)
        triggers = bench_maybe(tally)

        hr()
        report = tally.report("context")
        payload = {"suite": "context", "prune": prune, "split": split,
                   "compact": compact, "replay": replay,
                   "triggers": triggers, "report": report}
        save_report("context", payload)
        record("context", payload)
        return payload


if __name__ == "__main__":
    main()
