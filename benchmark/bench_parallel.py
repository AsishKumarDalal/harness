"""benchmark/bench_parallel.py — how well does the endpoint serve in parallel?

This matters for the harness in two places:

  * `delegate` spawns up to MAX_SUBAGENTS (3) children at once
    (subagents.py:134)
  * every tool call of one assistant turn runs in a ThreadPoolExecutor
    (main.py:226)

So: does the box actually run requests CONCURRENTLY, or is it a single
replica that queues them? The answer is visible in the numbers:

    parallel(N) ≈ serial(1)      -> it serves in parallel (throughput scales)
    parallel(N) ≈ N x serial(1)  -> it queues (latency grows with N)

The harness prints "✓ [1/3] goal (12.4s)" for every child
(subagents.py:115), so a queueing server makes every parallel gain
disappear.

Run:  .venv/bin/python benchmark/bench_parallel.py
"""

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (Tally, banner, check_endpoint, endpoint, hr, record,  # noqa: E402
                    save_report, server_info, stats)

from openai import OpenAI  # noqa: E402

PROMPT = ("Count from 1 to 40, one number per line, with a short comment after "
          "each number saying what it is. Take your time and be complete.")


def one_request(cli, model, index, out):
    """One streaming request; records its own timing."""
    t0 = time.perf_counter()
    first = None
    chars = 0
    reasoning = 0
    tokens = 0
    finish = None
    try:
        stream = cli.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": f"#{index}\n{PROMPT}"}],
            max_tokens=1024, stream=True, stream_options={"include_usage": True},
        )
        for chunk in stream:
            if getattr(chunk, "usage", None):
                tokens = chunk.usage.completion_tokens
            if not chunk.choices:
                continue
            if getattr(chunk.choices[0], "finish_reason", None):
                finish = chunk.choices[0].finish_reason
            d = chunk.choices[0].delta
            if d is None:
                continue
            r = (getattr(d, "reasoning_content", None)
                 or getattr(d, "reasoning", None))
            if r:
                if first is None:
                    first = time.perf_counter()
                reasoning += len(r)
            if d.content:
                if first is None:
                    first = time.perf_counter()
                chars += len(d.content)
    except Exception as e:
        out.append({"index": index, "error": f"{type(e).__name__}: {e}",
                    "wall_s": time.perf_counter() - t0, "ttft_ms": None,
                    "chars": 0, "reasoning_chars": 0, "tokens": 0})
        return
    end = time.perf_counter()
    out.append({"index": index,
                "wall_s": end - t0,
                "ttft_ms": (first - t0) * 1000 if first else None,
                "chars": chars, "reasoning_chars": reasoning,
                "tokens": tokens, "finish": finish})


def bench_parallelism(cli, model, tally: Tally):
    print("\n-- parallel vs serial --")
    rows = {}
    base_wall = None
    for n in (1, 2, 3, 4, 8):
        out = []
        t0 = time.perf_counter()
        threads = [threading.Thread(target=one_request,
                                    args=(cli, model, i, out))
                   for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        wall = time.perf_counter() - t0
        errors = [r for r in out if "error" in r]
        walls = [r["wall_s"] for r in out if "error" not in r]
        total_tokens = sum(r.get("tokens", 0) for r in out)
        ttfts = [r["ttft_ms"] for r in out if r.get("ttft_ms")]
        if n == 1:
            base_wall = wall
        speedup = (base_wall * n / wall) if wall else 0
        print(f"  N={n}: wall={wall:7.2f}s  per-request p50="
              f"{stats(walls).get('p50', 0):6.2f}s  "
              f"ttft p50={stats(ttfts).get('p50', 0):8.1f} ms  "
              f"tokens={total_tokens}  "
              f"speedup vs serial {n}x: {speedup:.2f}x  "
              f"errors={len(errors)}")
        if errors:
            print(f"      first error: {errors[0]['error'][:120]}")
        rows[str(n)] = {
            "wall_s": round(wall, 3),
            "per_request_s": stats(walls),
            "ttft_ms": stats(ttfts),
            "total_tokens": total_tokens,
            "speedup_vs_serial": round(speedup, 3),
            "errors": len(errors),
        }
    return rows


def bench_delegate(cli, model, tally: Tally):
    """The shape the harness actually uses: 3 children at once."""
    print("\n-- the delegate shape (3 children) --")
    out = []
    t0 = time.perf_counter()
    threads = [threading.Thread(target=one_request, args=(cli, model, 100 + i, out))
               for i in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall = time.perf_counter() - t0
    walls = [r["wall_s"] for r in out if "error" not in r]
    serial = sum(walls)
    print(f"  3 children: wall={wall:.2f}s  sum of the individual times={serial:.2f}s")
    print(f"  -> the children really ran at the same time: {wall < serial * 0.8}")
    tally.check("the three children overlapped", wall < serial * 0.8, True)
    return {"wall_s": round(wall, 3), "sum_individual_s": round(serial, 3),
            "requests": out}


def main():
    banner("BENCHMARK: the endpoint under parallel load")
    info = server_info()
    print(f"  endpoint: {info['base_url']}")
    print(f"  model   : {info['model']}")

    if not check_endpoint():
        print("\nthe endpoint is not reachable — nothing to measure.")
        return None

    base, key, model = endpoint()
    cli = OpenAI(api_key=key, base_url=base)
    tally = Tally()

    par = bench_parallelism(cli, model, tally)
    delegate = bench_delegate(cli, model, tally)

    hr()
    report = tally.report("parallelism")
    payload = {"suite": "parallel", "server": info, "parallelism": par,
               "delegate": delegate, "report": report}
    save_report("parallel", payload)
    record("parallel", payload)
    print("report written")
    return payload


if __name__ == "__main__":
    main()
