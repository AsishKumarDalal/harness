"""benchmark/run_all.py — run every suite and print one summary.

  Tier A (offline, deterministic, no model server):
      safety     tools     context     sessions     loop
  Tier B (live, needs the endpoint):
      model      agent     parallel

Usage:
    .venv/bin/python benchmark/run_all.py            # everything
    .venv/bin/python benchmark/run_all.py --offline  # only Tier A
    .venv/bin/python benchmark/run_all.py --live      # only Tier B

Every suite writes its own report to benchmark/results/<suite>.json and
appends a row to benchmark/results/<suite>.jsonl, so runs accumulate and
can be compared over time.
"""

import argparse
import importlib
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from common import banner, hr  # noqa: E402

OFFLINE = ["bench_safety", "bench_tools", "bench_context", "bench_sessions",
           "bench_loop"]
LIVE = ["bench_model", "bench_agent", "bench_parallel"]


def run(name: str) -> dict:
    t0 = time.perf_counter()
    try:
        mod = importlib.import_module(name)
        # The entry point is main() in most suites and run() in bench_loop
        # (which imports the harness' main module, so it cannot bind that
        # name to a function). Pick whichever is callable.
        entry = None
        for attr in ("main", "run"):
            cand = getattr(mod, attr, None)
            if callable(cand):
                entry = cand
                break
        if entry is None:
            raise RuntimeError(f"{name} has no callable entry point")
        entry()
        ok = True
        err = ""
    except SystemExit:
        ok = True
        err = ""
    except Exception as e:
        ok = False
        err = f"{type(e).__name__}: {e}"
        print(f"!! {name} failed: {err}")
    dt = time.perf_counter() - t0
    print(f"[{'ok' if ok else 'FAILED'}] {name} in {dt:.1f}s\n")
    return {"suite": name, "ok": ok, "seconds": round(dt, 1), "error": err}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--repeat", type=int, default=1,
                    help="repeats for the agent suite")
    args = ap.parse_args()

    if args.offline and not args.live:
        suites = OFFLINE
    elif args.live and not args.offline:
        suites = LIVE
    else:
        suites = OFFLINE + LIVE

    results = []
    for name in suites:
        banner(f"SUITE: {name}")
        if name == "bench_agent":
            sys.argv = [sys.argv[0], "--repeat", str(args.repeat)]
        results.append(run(name))
        hr()

    banner("SUMMARY")
    for r in results:
        print(f"  {r['suite']:16} {'ok' if r['ok'] else 'FAILED':>7}  "
              f"{r['seconds']:>7.1f}s  {r['error']}")
    failed = [r for r in results if not r["ok"]]
    print(f"\n{len(results) - len(failed)}/{len(results)} suites completed")
    return results


if __name__ == "__main__":
    main()
