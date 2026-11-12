"""Offline probe: the token estimate must never UNDER-count.

Regression test for the bug the benchmark found: context.tokens() used a
flat "4 characters = 1 token", but source code and JSON are really about
2.4 characters per token. Under-counting meant the compaction thresholds
fired far too late, and a request could go out larger than the model's
window.

The estimate is content-aware now, and pessimistic on purpose:
over-counting costs a little context, under-counting overflows the
window.

Run:  .venv/bin/python test/test_tokens.py
"""

import sys
from pathlib import Path

sys.dont_write_bytecode = True      # keep __pycache__ out of the project folder

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import context as ctx  # noqa: E402

passed = failed = 0


def check(label, got, want=True):
    global passed, failed
    ok = got == want
    print(("ok  " if ok else "FAIL"), label, "->", got)
    passed += ok
    failed += not ok


# --- the server's own counts for the reference content -------------------
# measured on the 36B endpoint with stream_options={"include_usage": True}
MEASURED = {
    "prose": (2106, 442),
    "words": (946, 222),
    "code": (1126, 461),
    "json": (1766, 741),
}

SAMPLES = {
    "prose": "This is a paragraph of ordinary English prose that a coding agent "
             "would read while it works on a task. " * 20,
    "words": "The quick brown fox jumps over the lazy dog. " * 20,
    "code": "def f(x):\n    return x + 1\n" * 40,
    "json": '{"key": "value", "n": 12345, "flag": true}\n' * 40,
}

# --- the estimate must never be below the truth -------------------------
print("-- never under-count (the dangerous direction) --")
for kind, (chars, real) in MEASURED.items():
    prompt = f"Read this and reply with the single word: ok\n\n{SAMPLES[kind]}"
    guess = ctx.tokens(prompt)
    check(f"{kind}: the estimate is at least the real count",
          guess >= real, True)

print("\n-- and it is not wildly over-counting either --")
for kind, (chars, real) in MEASURED.items():
    prompt = f"Read this and reply with the single word: ok\n\n{SAMPLES[kind]}"
    guess = ctx.tokens(prompt)
    over = (guess - real) / real
    check(f"{kind}: within 40% above the real count", over <= 0.40, True)
    print(f"     {kind}: real={real} guess={guess} ({over:+.1%})")

# --- the shape of the estimate ------------------------------------------
print("\n-- shape --")
check("empty text is 1 token, not 0", ctx.tokens(""), 1)
check("None is 1 token", ctx.tokens(None), 1)
check("longer text is never cheaper", ctx.tokens("x" * 8000) > ctx.tokens("x" * 4000), True)
check("code is counted denser than prose",
      ctx.tokens("def f(x):\n    return {x}\n" * 40)
      > ctx.tokens("the quick brown fox jumps over it. " * 40), True)
check("prose keeps the old 4-chars-per-token rule",
      ctx.tokens("x" * 4000), 1000)

print(f"\n{passed} passed, {failed} failed")
sys.exit(0 if failed == 0 else 1)
