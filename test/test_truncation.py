"""Offline probe: a truncated answer must be VISIBLE.

Regression test for the bug the benchmark found: llm.py hardcoded
max_tokens=4096 and never read finish_reason, so when the model ran out
of output budget the answer simply stopped mid-sentence and the harness
had no idea anything was wrong.

Now:
  * the output budget is config.MAX_TOKENS, not a literal 4096
  * the budget is clamped so prompt + answer fit the model's window
  * finish_reason is read, and a truncated turn says so

Run:  .venv/bin/python test/test_truncation.py
"""

import sys
from pathlib import Path

sys.dont_write_bytecode = True      # keep __pycache__ out of the project folder

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "benchmark"))

import config  # noqa: E402
import llm  # noqa: E402
from fake_model import Script, install_client  # noqa: E402

passed = failed = 0


def check(label, got, want=True):
    global passed, failed
    ok = got == want
    print(("ok  " if ok else "FAIL"), label, "->", repr(got))
    passed += ok
    failed += not ok


# --- the budget is configurable, not a literal ---------------------------
check("MAX_TOKENS is a setting", isinstance(config.MAX_TOKENS, int), True)
check("the default is generous", config.MAX_TOKENS >= 8192, True)

msgs = [{"role": "user", "content": "hello"}]
check("a small request gets the full budget", llm._max_tokens(msgs), config.MAX_TOKENS)

# a request that already fills the window must not also claim a huge output
big = [{"role": "user", "content": "x" * 400_000}]
check("a huge request is clamped", llm._max_tokens(big) < config.MAX_TOKENS, True)
check("the clamp never goes below 1024", llm._max_tokens(big) >= 1024, True)

# --- finish_reason is read ----------------------------------------------
script = Script(turns=[[("c", "a complete answer")]], finish_reason="stop")
install_client(script)
reply = llm.chat(msgs)
check("a finished answer is not truncated", reply.truncated, False)
check("finish_reason is 'stop'", reply.finish_reason, "stop")

script = Script(turns=[[("c", "half an ans")]], finish_reason="length")
install_client(script)
reply = llm.chat(msgs)
check("a cut-off answer IS truncated", reply.truncated, True)
check("finish_reason is 'length'", reply.finish_reason, "length")

# --- the CLI says so ----------------------------------------------------
import main  # noqa: E402

check("main can read the flag", hasattr(reply, "truncated"), True)

print(f"\n{passed} passed, {failed} failed")
sys.exit(0 if failed == 0 else 1)
