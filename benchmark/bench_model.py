"""benchmark/bench_model.py — the live model: latency, tokens, truncation.

This suite talks to the real endpoint (the 36B on 2x T4) with the SAME
parameters the harness uses (llm.py:129-135):

    model=<machine model>, max_tokens=4096, stream=True,
    stream_options={"include_usage": True}

Measured:
  * TTFT      — time to the first token (and to the first ANSWER token,
                which for a reasoning model is much later)
  * throughput— tokens/second, split into reasoning and answer
  * truncation— how often finish_reason == "length". This matters a lot:
                the harness hardcodes max_tokens=4096 and IGNORES
                finish_reason (llm.py:163), so a turn where the model
                spends the whole budget thinking returns an EMPTY answer
                and the failure is invisible.
  * the token estimator — context.tokens() assumes 4 chars = 1 token
                (context.py:40). The server reports the true
                prompt_tokens, so the error can be measured exactly.

Run:  .venv/bin/python benchmark/bench_model.py
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (Tally, banner, check_endpoint, endpoint, hr, record,  # noqa: E402
                    save_report, server_info, stats)

from openai import OpenAI  # noqa: E402

import config  # noqa: E402

# the output budget the harness actually uses (config.MAX_TOKENS, default
# 16384). It used to be a literal 4096 in llm.py, which truncated 2 of 3
# realistic coding turns — see the benchmark README.
MAX_TOKENS = config.MAX_TOKENS


def client():
    base, key, model = endpoint()
    return OpenAI(api_key=key, base_url=base), model


def stream_once(cli, model, prompt, max_tokens=MAX_TOKENS, capture_reasoning=True):
    """One streaming call; returns timing + token accounting."""
    t0 = time.perf_counter()
    first_any = None
    first_content = None
    content = ""
    reasoning = ""
    finish = None
    usage = None

    stream = cli.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
        stream=True,
        stream_options={"include_usage": True},
    )
    for chunk in stream:
        if getattr(chunk, "usage", None):
            usage = chunk.usage
        if not chunk.choices:
            continue
        choice = chunk.choices[0]
        if getattr(choice, "finish_reason", None):
            finish = choice.finish_reason
        delta = choice.delta
        if delta is None:
            continue
        now = time.perf_counter()
        if first_any is None:
            first_any = now
        # the server sends the reasoning under 'reasoning' (some servers
        # use 'reasoning_content'); the harness reads both — so does this
        r = (getattr(delta, "reasoning_content", None)
             or getattr(delta, "reasoning", None))
        if r:
            if first_any is None:
                first_any = now
            reasoning += r
        if delta.content:
            if first_content is None:
                first_content = now
            content += delta.content

    end = time.perf_counter()
    return {
        "ttft_any_ms": (first_any - t0) * 1000 if first_any else None,
        "ttft_content_ms": (first_content - t0) * 1000 if first_content else None,
        "total_ms": (end - t0) * 1000,
        "content": content,
        "content_chars": len(content),
        "reasoning_chars": len(reasoning),
        "finish_reason": finish,
        "prompt_tokens": getattr(usage, "prompt_tokens", None) if usage else None,
        "completion_tokens": getattr(usage, "completion_tokens", None) if usage else None,
        "total_tokens": getattr(usage, "total_tokens", None) if usage else None,
    }


def bench_latency(cli, model, tally: Tally, repeats=3):
    """TTFT and throughput on a small, a medium and a big prompt."""
    print("\n-- latency and throughput --")
    prompts = {
        "tiny": "Reply with exactly the word: ok",
        "medium": "Explain in one short paragraph why the sky is blue.",
        "reasoning": ("A farmer has 3 fields. The first yields 7 bags, the second "
                      "twice as many as the first, the third half of the second "
                      "plus 3. How many bags in total? Show the steps."),
    }
    rows = {}
    for name, prompt in prompts.items():
        samples = []
        for i in range(repeats):
            r = stream_once(cli, model, prompt)
            samples.append(r)
            print(f"  {name:10} ttft_any={r['ttft_any_ms']:8.1f} ms  "
                  f"ttft_answer={str(round(r['ttft_content_ms'], 1)) if r['ttft_content_ms'] else 'none':>9} ms  "
                  f"total={r['total_ms']:9.1f} ms  "
                  f"tokens={r['completion_tokens']}  finish={r['finish_reason']}")
        rows[name] = {
            "ttft_any_ms": stats([s["ttft_any_ms"] for s in samples]),
            "ttft_content_ms": stats([s["ttft_content_ms"] for s in samples]),
            "total_ms": stats([s["total_ms"] for s in samples]),
            "completion_tokens": stats([s["completion_tokens"] for s in samples]),
            "finish_reasons": [s["finish_reason"] for s in samples],
        }
    return rows


def bench_truncation(cli, model, tally: Tally, repeats=3):
    """Does a hard turn eat the whole 4096-token budget on reasoning alone?"""
    print("\n-- truncation (finish_reason) --")
    print(f"   output budget: {MAX_TOKENS} tokens (config.MAX_TOKENS)")
    hard = ("You are a senior engineer. Review this Python function and rewrite it "
            "with full type hints, docstrings, error handling and unit tests:\n\n"
            "def parse(s):\n"
            "    parts = s.split(',')\n"
            "    return [float(p) for p in parts if p]\n\n"
            "Then explain every decision you made in detail.")
    rows = []
    for i in range(repeats):
        r = stream_once(cli, model, hard)
        rows.append(r)
        empty = r["content_chars"] == 0
        print(f"  run {i+1}: finish={r['finish_reason']}  "
              f"completion_tokens={r['completion_tokens']}  "
              f"answer_chars={r['content_chars']}  "
              f"reasoning_chars={r['reasoning_chars']}  "
              f"{'<-- EMPTY ANSWER' if empty else ''}")
    truncated = [r for r in rows if r["finish_reason"] == "length"]
    empty_answers = [r for r in rows if r["content_chars"] == 0]
    print(f"  truncated: {len(truncated)}/{len(rows)}   "
          f"empty answers: {len(empty_answers)}/{len(rows)}")

    # A KNOWN GAP, not a failing assertion: llm.py never reads
    # finish_reason, so a truncated turn is invisible to the harness.
    import pathlib
    llm_src = pathlib.Path(__file__).resolve().parent.parent / "llm.py"
    reads_finish_reason = "finish_reason" in llm_src.read_text(encoding="utf-8")
    print(f"  llm.py reads finish_reason: {reads_finish_reason}"
          f"{'' if reads_finish_reason else '   <-- truncated turns are invisible'}")
    return {"runs": [{k: v for k, v in r.items() if k != "content"}
                     for r in rows],
            "truncated": len(truncated), "empty_answers": len(empty_answers),
            "total": len(rows),
            "llm_reads_finish_reason": reads_finish_reason,
            "truncation_rate": round(len(truncated) / len(rows), 3)}


def bench_token_estimator(cli, model, tally: Tally):
    """How wrong is the 4-chars-per-token guess?"""
    print("\n-- the token estimator (context.py:40) --")
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import context as ctx

    samples = {
        "words": ("The quick brown fox jumps over the lazy dog. " * 20),
        "code": ("def f(x):\n    return x + 1\n" * 40),
        "json": ('{"key": "value", "n": 12345, "flag": true}\n' * 40),
        "prose": ("This is a paragraph of ordinary English prose that a coding "
                  "agent would read while it works on a task. " * 20),
    }
    rows = {}
    for name, text in samples.items():
        prompt = f"Read this and reply with the single word: ok\n\n{text}"
        r = stream_once(cli, model, prompt)
        real = r["prompt_tokens"]
        guess = ctx.tokens(prompt)
        ratio = real / guess if guess else 0
        print(f"  {name:6} chars={len(prompt):>6}  server_tokens={real:>6}  "
              f"harness_guess={guess:>6}  real/guess={ratio:.3f}  "
              f"error={round(100 * (guess - real) / real, 1):+.1f}%")
        rows[name] = {"chars": len(prompt), "server_tokens": real,
                      "harness_guess": guess, "ratio": round(ratio, 4),
                      "error_pct": round(100 * (guess - real) / real, 1)}

    ratios = [v["ratio"] for v in rows.values()]
    print(f"  mean real/guess ratio: {sum(ratios)/len(ratios):.3f}  "
          f"(1.0 = the guess is perfect)")
    # the harness reserves CONTEXT_RESERVE=12000 of the 50000 window
    # based on this estimate, so a 20% error is 2400 tokens of drift
    worst = max(abs(v["error_pct"]) for v in rows.values())
    print(f"  worst error: {worst:.1f}%  -> on a 38000 budget that is "
          f"{round(38000 * worst / 100)} tokens of drift")
    return rows


def bench_prompt_sweep(cli, model, tally: Tally):
    """Latency as the prompt grows — where is the practical cliff?"""
    print("\n-- prompt size sweep (context window) --")
    filler = ("The system is a small Python agent. It reads files, runs commands "
              "and edits code. " * 40)
    rows = {}
    for approx_tokens in (500, 2000, 8000, 20000, 40000):
        text = filler
        while ctx_tokens(text) < approx_tokens:
            text += filler
        prompt = ("Summarise the following context in one sentence:\n\n" + text)
        t0 = time.perf_counter()
        r = stream_once(cli, model, prompt)
        print(f"  ~{approx_tokens:>6} tok  prompt_tokens={r['prompt_tokens']:>6}  "
              f"ttft={str(round(r['ttft_content_ms'], 1)) if r['ttft_content_ms'] else 'none':>9} ms  "
              f"total={r['total_ms']:9.1f} ms  finish={r['finish_reason']}")
        rows[str(approx_tokens)] = {
            "prompt_tokens": r["prompt_tokens"],
            "ttft_content_ms": r["ttft_content_ms"],
            "total_ms": r["total_ms"],
            "finish_reason": r["finish_reason"],
            "answer_chars": r["content_chars"],
        }
    return rows


def ctx_tokens(text):
    """A local copy of the harness' estimator (no import side effects)."""
    return max(1, len(text) // 4)


def main():
    banner("BENCHMARK: the live model — latency, tokens, truncation")
    info = server_info()
    print(f"  endpoint: {info['base_url']}")
    print(f"  model   : {info['model']}")
    print(f"  python  : {info['python']}   cpus: {info['cpu_count']}")

    if not check_endpoint():
        print("\nthe endpoint is not reachable — nothing to measure.")
        return None

    cli, model = client()
    tally = Tally()

    latency = bench_latency(cli, model, tally)
    truncation = bench_truncation(cli, model, tally)
    estimator = bench_token_estimator(cli, model, tally)
    sweep = bench_prompt_sweep(cli, model, tally)

    hr()
    report = tally.report("live model")
    payload = {"suite": "model", "server": info, "latency": latency,
               "truncation": truncation, "token_estimator": estimator,
               "prompt_sweep": sweep, "report": report}
    save_report("model", payload)
    record("model", payload)
    print("report written")
    return payload


if __name__ == "__main__":
    main()
