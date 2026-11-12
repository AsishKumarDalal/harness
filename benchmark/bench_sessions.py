"""benchmark/bench_sessions.py — the notebook: write-through, resume, search.

The SQLite notebook (sessions.py) is the harness's memory. Four
properties are load-bearing and each has a benchmark here:

  1. WRITE-THROUGH — every message is stored the moment it happens, so a
     crash never loses the conversation (sessions.py:147).
  2. ARCHIVE, NEVER DELETE — compaction marks rows active=0; the text
     stays reachable through /search and session_search
     (docs/README.md:51).
  3. RESUME — a session can be reloaded and the history rebuilt exactly.
  4. SEARCH SCALING — sessions.search() uses LIKE '%q%' on the content
     column, which cannot use an index. It is measured here so the cost
     is known before the notebook gets big.

Run:  .venv/bin/python benchmark/bench_sessions.py
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (Sandbox, Tally, banner, finish, hr, record,  # noqa: E402
                    save_report, stats, use_sandbox)

import config  # noqa: E402
import sessions  # noqa: E402


def bench_write_through(tally: Tally):
    print("\n-- write-through --")
    sid = sessions.new_session(title="wt", system_prompt="sys", model="fake",
                               cwd=str(config.START_DIR))
    samples = []
    for i in range(500):
        t0 = time.perf_counter()
        sessions.add_message(sid, "user", f"message number {i} with some text")
        samples.append(time.perf_counter() - t0)
    st = stats(samples)
    print(f"  insert p50={st['p50']*1000:.3f} ms  p95={st['p95']*1000:.3f} ms  "
          f"max={st['max']*1000:.3f} ms")
    print(f"  throughput: {round(1 / st['mean'])} inserts/s")

    rows = sessions.db().execute(
        "SELECT COUNT(*) FROM messages WHERE session_id=?", (sid,)).fetchone()[0]
    tally.check("all 500 messages are stored", rows, 500)
    tally.check("the median insert is under 2 ms", st["p50"] < 0.002, True)
    return {"insert": st, "rows": rows}


def bench_resume(tally: Tally):
    print("\n-- resume --")
    sid = sessions.new_session(title="resume", system_prompt="sys", model="fake",
                               cwd=str(config.START_DIR))
    for i in range(50):
        sessions.add_message(sid, "user", f"question {i}")
        sessions.add_message(sid, "assistant", f"answer {i}")

    # simulate a crash: drop the thread's connection, then read back
    sessions._local.__dict__.clear()
    hist = sessions.load_messages(sid)
    print(f"  reloaded {len(hist)} messages")
    tally.check("every message comes back", len(hist), 100)
    tally.check("the order is preserved", hist[0]["content"], "question 0")
    tally.check("the roles are preserved", hist[1]["role"], "assistant")
    return {"reloaded": len(hist)}


def bench_archive(tally: Tally):
    print("\n-- archive, never delete --")
    sid = sessions.new_session(title="archive", system_prompt="sys", model="fake",
                               cwd=str(config.START_DIR))
    hist = [{"role": "system", "content": "sys"}]
    for i in range(20):
        hist.append({"role": "user", "content": f"u{i}"})
        hist.append({"role": "assistant", "content": f"a{i}"})
    sessions.sync(sid, hist)

    # now the live history loses the middle (what a compaction does)
    trimmed = [hist[0]] + hist[-4:]
    sessions.sync(sid, trimmed)

    total = sessions.db().execute(
        "SELECT COUNT(*) FROM messages WHERE session_id=?", (sid,)).fetchone()[0]
    active = sessions.db().execute(
        "SELECT COUNT(*) FROM messages WHERE session_id=? AND active=1",
        (sid,)).fetchone()[0]
    archived = sessions.db().execute(
        "SELECT COUNT(*) FROM messages WHERE session_id=? AND active=0",
        (sid,)).fetchone()[0]
    print(f"  rows={total} active={active} archived={archived}")
    tally.check("the dropped rows are archived, not deleted", archived > 0, True)
    tally.check("total rows never shrink", total, 41)   # 1 system + 20x2

    # and they are still findable
    hits = sessions.search("u3", limit=5)
    print(f"  search('u3') -> {len(hits)} hits")
    tally.check("archived content is still searchable", len(hits) > 0, True)
    return {"total": total, "active": active, "archived": archived}


def bench_search_scaling(tally: Tally):
    print("\n-- search scaling (LIKE '%q%' cannot use an index) --")
    rows = {}
    for n in (100, 1000, 5000):
        sid = sessions.new_session(title=f"scale{n}", system_prompt="s",
                                   model="fake", cwd=str(config.START_DIR))
        for i in range(n):
            sessions.add_message(sid, "user", f"row {i} " + "filler " * 20)
        samples = []
        for _ in range(10):
            t0 = time.perf_counter()
            sessions.search("row 42", limit=5)
            samples.append(time.perf_counter() - t0)
        st = stats(samples)
        rows[f"{n}"] = st
        print(f"  {n:>5} messages  p50={st['p50']*1000:8.3f} ms")
    tally.check("search stays under 250 ms at 5000 messages",
                rows["5000"]["p50"] < 0.25, True)
    return rows


def bench_export(tally: Tally):
    print("\n-- export --")
    sid = sessions.new_session(title="export", system_prompt="sys", model="fake",
                               cwd=str(config.START_DIR))
    for i in range(10):
        sessions.add_message(sid, "user", f"u{i}")
    t0 = time.perf_counter()
    path = sessions.export_session(sid)
    dt = time.perf_counter() - t0
    lines = len(Path(path).read_text(encoding="utf-8").splitlines())
    print(f"  exported {lines} JSONL lines in {dt*1000:.2f} ms -> {path}")
    tally.check("the export holds every message", lines, 11)
    return {"lines": lines, "seconds": dt}


def main():
    banner("BENCHMARK: session notebook — write-through, resume, search")
    with Sandbox("sessions") as sb:
        use_sandbox(sb, mode="auto")
        sb.write("main.py", "print(1)\n")

        tally = Tally()
        wt = bench_write_through(tally)
        rs = bench_resume(tally)
        ar = bench_archive(tally)
        sc = bench_search_scaling(tally)
        ex = bench_export(tally)

        hr()
        report = tally.report("sessions")
        payload = {"suite": "sessions", "write_through": wt, "resume": rs,
                   "archive": ar, "search_scaling": sc, "export": ex,
                   "report": report}
        save_report("sessions", payload)
        record("sessions", payload)
        finish(payload)


if __name__ == "__main__":
    main()
