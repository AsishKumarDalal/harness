"""benchmark/bench_loop.py — the agent loop itself: overhead and invariants.

Tier A: a scripted fake model drives the REAL loop (main.agent()), so
this measures the harness' own cost with the model time removed — the
part that is 100% the harness' responsibility.

Measured:
  * overhead per turn (everything except the model)
  * where that overhead goes (tools / notebook / rendering)
  * the protocol invariants that must never break
      - tool results go back in CALL order, even when the tools finish
        out of order (docs/README.md:55)
      - parallel tool calls really run in parallel
      - MAX_TURNS stops the loop
      - a tool error comes back as a string, never an exception

Run:  .venv/bin/python benchmark/bench_loop.py
"""

import io
import contextlib
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (Sandbox, Tally, banner, finish, hr, record,  # noqa: E402
                    save_report, use_sandbox)

import config  # noqa: E402
import fake_model  # noqa: E402
import main  # noqa: E402
import sessions  # noqa: E402
import tools  # noqa: E402
from messages import Conversation  # noqa: E402


def instrument():
    """Wrap the hot paths to see where the harness spends its time."""
    timings = {"tool": 0.0, "db": 0.0, "tool_calls": 0}

    real_run_tool = tools.run_tool
    real_add_message = sessions.add_message
    real_sync = sessions.sync

    def timed_run_tool(call):
        t0 = time.perf_counter()
        try:
            return real_run_tool(call)
        finally:
            timings["tool"] += time.perf_counter() - t0
            timings["tool_calls"] += 1

    def timed_add_message(*a, **kw):
        t0 = time.perf_counter()
        try:
            return real_add_message(*a, **kw)
        finally:
            timings["db"] += time.perf_counter() - t0

    def timed_sync(*a, **kw):
        t0 = time.perf_counter()
        try:
            return real_sync(*a, **kw)
        finally:
            timings["db"] += time.perf_counter() - t0

    tools.run_tool = timed_run_tool
    sessions.add_message = timed_add_message
    sessions.sync = timed_sync
    main.run_tool = timed_run_tool       # main.py holds its own reference
    return timings, (real_run_tool, real_add_message, real_sync)


def restore(real):
    tools.run_tool, sessions.add_message, sessions.sync = real
    main.run_tool = real[0]


def fresh_convo(title="loop"):
    sid = sessions.new_session(title=title, system_prompt="sys", model="fake",
                               cwd=str(config.START_DIR))
    convo = Conversation("sys", sid)
    main.convo = convo
    return convo


def bench_overhead(tally: Tally):
    """The harness' own cost, with the model replaced by a script."""
    print("\n-- overhead per turn (model time removed) --")
    timings, real = instrument()
    try:
        script = fake_model.Script(turns=[
            [("c", "listing"), fake_model.TC("list_files", "{}")],
            [("c", "reading"), fake_model.TC("read_file", '{"path": "main.py"}')],
            [("c", "searching"), fake_model.TC("search_files", '{"needle": "x"}')],
            [("c", "done")],
        ])
        fake_model.install(script)
        fresh_convo()

        t0 = time.perf_counter()
        with contextlib.redirect_stdout(io.StringIO()):
            main.agent("what is in this project?")
        total = time.perf_counter() - t0

        tool_time = timings["tool"]
        db_time = timings["db"]
        other = total - tool_time - db_time
        print(f"  total loop time : {total*1000:8.3f} ms  ({script.used} model turns)")
        print(f"  tool execution  : {tool_time*1000:8.3f} ms  "
              f"({timings['tool_calls']} calls)")
        print(f"  notebook writes : {db_time*1000:8.3f} ms")
        print(f"  everything else : {other*1000:8.3f} ms  (rendering, history)")
        print(f"  per model turn  : {(total / max(script.used, 1))*1000:8.3f} ms")

        tally.check("the loop finished", script.used, 4)
        tally.check("every tool call was executed", timings["tool_calls"], 3)
        tally.check("a turn costs well under 50 ms of harness time",
                    total / max(script.used, 1) < 0.05, True)
        return {"total_ms": total * 1000, "tool_ms": tool_time * 1000,
                "db_ms": db_time * 1000, "other_ms": other * 1000,
                "turns": script.used,
                "per_turn_ms": (total / max(script.used, 1)) * 1000}
    finally:
        restore(real)


def bench_call_order(tally: Tally):
    """Tool results must go back in CALL order, even out of order in time."""
    print("\n-- protocol: results go back in call order --")
    # four commands with different durations: they FINISH out of order
    # (1.2s, 0.1s, 0.9s, 0.3s) but must be REPORTED in call order.
    # serial would take 2.5s; parallel takes ~1.2s.
    script = fake_model.Script(turns=[
        [fake_model.TC("run_command", '{"command": "sleep 1.2 && echo FIRST"}', index=0),
         fake_model.TC("run_command", '{"command": "sleep 0.1 && echo SECOND"}', index=1),
         fake_model.TC("run_command", '{"command": "sleep 0.9 && echo THIRD"}', index=2),
         fake_model.TC("run_command", '{"command": "sleep 0.3 && echo FOURTH"}', index=3)],
        [("c", "all done")],
    ])
    fake_model.install(script)
    convo = fresh_convo("order")

    t0 = time.perf_counter()
    with contextlib.redirect_stdout(io.StringIO()):
        main.agent("run all four")
    dt = time.perf_counter() - t0

    tool_msgs = [m.get("content", "") for m in convo.history if m.get("role") == "tool"]
    print(f"  wall clock: {dt:.3f} s   (serial would be ~2.5 s)")
    for i, m in enumerate(tool_msgs):
        first = m.strip().splitlines()[0] if m.strip() else ""
        print(f"  tool[{i}] = {first!r}")

    tally.check("every tool result came back", len(tool_msgs), 4)
    tally.check("result 0 is the FIRST call", "FIRST" in tool_msgs[0], True)
    tally.check("result 1 is the SECOND call", "SECOND" in tool_msgs[1], True)
    tally.check("result 2 is the THIRD call", "THIRD" in tool_msgs[2], True)
    tally.check("result 3 is the FOURTH call", "FOURTH" in tool_msgs[3], True)
    tally.check("the commands ran in parallel (not 2.5 s serial)", dt < 1.8, True)
    return {"wall_clock": dt,
            "order": [m.strip().splitlines()[0] for m in tool_msgs]}


def bench_error_recovery(tally: Tally):
    """A tool error must come back as a string, and the loop must survive it."""
    print("\n-- protocol: errors are strings, never exceptions --")
    script = fake_model.Script(turns=[
        [fake_model.TC("read_file", '{"path": "does-not-exist.txt"}')],
        [fake_model.TC("run_command", '{"command": "exit 3"}')],
        [("c", "recovered")],
    ])
    fake_model.install(script)
    convo = fresh_convo("errors")

    with contextlib.redirect_stdout(io.StringIO()):
        out = main.agent("read a missing file and run a failing command")

    tool_msgs = [m.get("content", "") for m in convo.history if m.get("role") == "tool"]
    print(f"  tool results: {[m.strip().splitlines()[0] for m in tool_msgs]}")
    tally.check("the missing file produced an error string",
                "Error" in tool_msgs[0], True)
    tally.check("the failing command produced an error string",
                "exit=3" in tool_msgs[1], True)
    tally.check("the loop survived both errors", "recovered" in (out or ""), True)
    return {"results": [m.strip().splitlines()[0] for m in tool_msgs]}


def bench_max_turns(tally: Tally):
    """The loop must stop at MAX_TURNS instead of spinning forever."""
    print("\n-- protocol: the turn cap holds --")
    # every turn asks for another tool call -> the loop must stop
    script = fake_model.Script(turns=[
        [fake_model.TC("list_files", "{}")] for _ in range(main.MAX_TURNS + 5)
    ])
    fake_model.install(script)
    fresh_convo("turns")

    with contextlib.redirect_stdout(io.StringIO()):
        out = main.agent("loop forever")

    print(f"  model turns used: {script.used} (cap is {main.MAX_TURNS})")
    tally.check("the loop stopped at the cap", script.used <= main.MAX_TURNS + 1, True)
    tally.check("the user is told it stopped", "stopped after" in (out or ""), True)
    return {"turns_used": script.used, "cap": main.MAX_TURNS}


def run():
    banner("BENCHMARK: the agent loop — overhead and protocol invariants")
    with Sandbox("loop") as sb:
        use_sandbox(sb, mode="auto")
        sb.write("main.py", "def main():\n    print('x')\n")
        sb.write("other.py", "y = 2\n")
        sb.write("notes.md", "some notes\n")

        tally = Tally()
        overhead = bench_overhead(tally)
        order = bench_call_order(tally)
        errors = bench_error_recovery(tally)
        turns = bench_max_turns(tally)

        hr()
        report = tally.report("agent loop")
        payload = {"suite": "loop", "overhead": overhead, "call_order": order,
                   "error_recovery": errors, "max_turns": turns, "report": report}
        save_report("loop", payload)
        record("loop", payload)
        finish(payload)


if __name__ == "__main__":
    run()
