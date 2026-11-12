"""benchmark/run_all.py — run every suite and print one summary.

  Tier A (offline, deterministic, no model server):
      safety     tools     context     sessions     loop
  Tier B (live, needs the endpoint):
      model      agent     parallel

Each suite runs as its own process (so one broken suite cannot take the
others down, and the exit codes are real), and exits non-zero when a
check fails — which is what makes this usable as a CI gate.

Usage:
    .venv/bin/python benchmark/run_all.py            # everything
    .venv/bin/python benchmark/run_all.py --offline  # only Tier A
    .venv/bin/python benchmark/run_all.py --live      # only Tier B

Every suite writes its own report to benchmark/results/<suite>.json and
appends a row to benchmark/results/<suite>.jsonl, so runs accumulate and
can be compared over time.
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

OFFLINE = ["bench_safety", "bench_tools", "bench_context", "bench_sessions",
           "bench_loop"]
LIVE = ["bench_model", "bench_agent", "bench_parallel"]


def run(name: str) -> dict:
    """Run one suite in its own process."""
    t0 = time.perf_counter()
    cmd = [sys.executable, str(HERE / f"{name}.py")]
    try:
        proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                              timeout=3600)
        ok = proc.returncode == 0
        err = "" if ok else (proc.stdout[-600:] + proc.stderr[-600:])
    except subprocess.TimeoutExpired:
        ok, err = False, "timed out"
    dt = time.perf_counter() - t0
    print(f"[{'ok' if ok else 'FAILED'}] {name} in {dt:.1f}s")
    if not ok:
        print(err.strip())
    return {"suite": name, "ok": ok, "seconds": round(dt, 1), "error": err[:200]}


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
        cmd = [sys.executable, str(HERE / f"{name}.py")]
        if name == "bench_agent":
            cmd += ["--repeat", str(args.repeat)]
        t0 = time.perf_counter()
        print("=" * 68)
        print(f" SUITE: {name}")
        print("=" * 68)
        try:
            proc = subprocess.run(cmd, cwd=ROOT, capture_output=True,
                                  text=True, timeout=3600)
            ok = proc.returncode == 0
            err = "" if ok else (proc.stdout[-800:] + proc.stderr[-400:])
            if ok:
                print(proc.stdout.strip()[-1500:])
        except subprocess.TimeoutExpired:
            ok, err = False, "timed out"
        dt = time.perf_counter() - t0
        print(f"[{'ok' if ok else 'FAILED'}] {name} in {dt:.1f}s\n")
        results.append({"suite": name, "ok": ok, "seconds": round(dt, 1),
                        "error": err[:200]})

    print("=" * 68)
    print(" SUMMARY")
    print("=" * 68)
    for r in results:
        print(f"  {r['suite']:16} {'ok' if r['ok'] else 'FAILED':>7}  "
              f"{r['seconds']:>7.1f}s  {r['error']}")
    failed = [r for r in results if not r["ok"]]
    print(f"\n{len(results) - len(failed)}/{len(results)} suites completed")
    if failed:
        print(f"FAILED: {', '.join(r['suite'] for r in failed)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
