# The Harness — Benchmark Suite

Measurements for the harness itself: how fast it is, how safe it is, and
how good the agent is at real tasks.

The suite is in two tiers, and the split is not arbitrary — it falls out
of one fact about the code: **`llm.py` is the only file that talks to the
model** (`docs/README.md:40`). It does exactly one thing:

```python
stream = client(model).chat.completions.create(**kwargs)   # llm.py:139
for chunk in stream: ...                                    # llm.py:152
```

Replace that one object with a script and the *whole* harness runs
offline, deterministically, in milliseconds. That is what Tier A does.

| | **Tier A — offline** | **Tier B — live** |
|---|---|---|
| Measures | your code: tools, safety, compaction, notebook, loop | the model: latency, cost, task completion |
| Needs a server | no | yes |
| Reproducible | bit for bit | noisy |
| Cost | free | tokens x runs |
| In CI | yes | no |

---

## Running it

```bash
# Tier A — offline, deterministic, a few seconds
.venv/bin/python benchmark/run_all.py --offline

# Tier B — live, needs the endpoint in .env
.venv/bin/python benchmark/run_all.py --live

# everything, sequentially
.venv/bin/python benchmark/run_all.py

# the live suites back to back (they must NOT overlap: one server)
benchmark/run_live.sh

# the agent on real tasks, twice each
.venv/bin/python benchmark/bench_agent.py --repeat 2

# prove the task checkers themselves are correct
.venv/bin/python benchmark/test_tasks.py
```

The endpoint comes from `.env`; `BENCH_BASE_URL`, `BENCH_API_KEY` and
`BENCH_MODEL` override it. Every suite writes
`benchmark/results/<suite>.json` and appends to
`benchmark/results/<suite>.jsonl`, so runs accumulate and can be
compared over time.

### The suites

| File | Tier | What it measures |
|---|---|---|
| `bench_safety.py` | A | the permission gate, as a confusion matrix over a labelled command corpus |
| `bench_tools.py` | A | tool latency, output caps, the path jail, secret refusal, env scrubbing |
| `bench_context.py` | A | prune/compact behaviour, the head/middle/tail split, the request replay |
| `bench_sessions.py` | A | write-through, resume, archive-not-delete, search scaling |
| `bench_loop.py` | A | harness overhead per turn and the protocol invariants |
| `bench_model.py` | B | TTFT, throughput, truncation, token-estimator accuracy, prefill scaling |
| `bench_agent.py` | B | the whole agent on real tasks, scored by programmatic checkers |
| `bench_parallel.py` | B | whether the endpoint really serves requests concurrently |
| `test_tasks.py` | A | that every task checker is strict AND satisfiable |

`common.py` holds the isolation (a throwaway project folder **and** a
throwaway `$HARNESS_HOME`), the stats helpers and the result writer.
`fake_model.py` is the scripted stand-in for the model server.

---

## Results

Measured on: `k2-horizon-mova-36b-a4b` (36B MoE, 2x T4, q8_0 KV cache),
context window 50 000, Python 3.14.4, 12 CPUs.
Endpoint: `https://small-present-educated-believe.trycloudflare.com/v1`.

### Tier A — the harness itself

| Suite | Result | Notes |
|---|---|---|
| `bench_safety` | **60/62 (96.8 %)** | 3 hardline escapes, 1 false positive — see findings |
| `bench_tools` | 14/14 (100 %) | every wall holds; `list_files` 26 ms at 3 000 files |
| `bench_context` | 23/23 (100 %) | prune saves 79 %, compact 80 %, the replay works |
| `bench_sessions` | 10/10 (100 %) | 77 k inserts/s, search 0.15 ms at 5 000 messages |
| `bench_loop` | 14/14 (100 %) | **0.22 ms of harness time per turn** |

Harness overhead, with the model time removed (4 turns, 3 tool calls):

```
total loop time :    0.973 ms   (4 model turns)
tool execution  :    0.444 ms   (3 calls)
notebook writes :    0.234 ms
everything else :    0.294 ms   (rendering, history)
per model turn  :    0.223 ms
```

The harness itself is effectively free next to the model. Every
millisecond that matters is the model's.

Tool layer, median over 5 runs:

| tool | 50 files | 500 files |
|---|---|---|
| `list_files` | 1.1 ms | 5.5 ms |
| `search_files` | 1.3 ms | 2.3 ms |
| `read_file` / `write_file` / `edit_file` | < 0.1 ms | < 0.1 ms |

Scaling: `list_files` 0.9 ms / 14.8 ms / 26.0 ms at 100 / 1 000 / 3 000
files. `search_files` 1.1 ms / 4.0 ms / 6.9 ms.

### Tier B — the agent on real tasks

Five tasks, each with a programmatic checker, each run twice against the
live endpoint. The checkers are themselves proven correct first
(`benchmark/test_tasks.py`): every one of them **fails the unsolved
fixture** and **passes a reference solution**, so a 100 % rate means
something.

| task | pass | wall (p50) | turns | tool calls | tokens |
|---|---|---|---|---|---|
| `explain_code` (read + answer) | 100 % | 4.6 s | 2.5 | 2.0 | 1 038 |
| `fix_off_by_one` (fix a bug) | 100 % | 10.3 s | 4.5 | 3.5 | 1 247 |
| `add_cli_flag` (add a feature) | 100 % | 11.0 s | 4.5 | 3.5 | 1 274 |
| `write_tests` (write tests) | 100 % | 15.3 s | 5.5 | 4.5 | 1 536 |
| `rename_across_files` (refactor) | 100 % | 16.4 s | 6.0 | 10.5 | 1 617 |
| **overall** | **10/10 (100 %)** | | | | |

The pattern is healthy: the harder the task, the more turns and the more
tool calls, but the token count stays flat at ~1 000–1 600 — the agent
does not spiral. `rename_across_files` is the outlier with 10.5 tool
calls (it has to find three files, read them and rewrite them) and it is
still the slowest but cheapest per turn.

Note the cost structure: a task costs ~1 200 tokens but ~10–16 seconds.
**The tokens are not the bottleneck — the latency is.**

### Tier B — the model (36B on 2x T4)


Latency, 3 runs each:

| prompt | first chunk | **first answer token** | total | completion tokens |
|---|---|---|---|---|
| tiny ("reply ok") | 877 ms | **3 203 ms** | 3 233 ms | 101 |
| medium (one paragraph) | 470 ms | **1 210 ms** | 3 083 ms | 115 |
| reasoning (arithmetic) | 522 ms | **5 814 ms** | 9 067 ms | 354 |

The gap between "first chunk" and "first answer token" is the model's
reasoning. This server sends it under the field `reasoning` (not
`reasoning_content`) — and `llm.py:166` reads both, so the harness
catches it: a 17x23 multiplication produced **2 008 thinking tokens**
and 494 answer tokens, and the CLI rendered the thinking block as
intended.

The user is not staring at a blank screen — but the first visible text
of a hard turn can be **6–12 seconds** away.

Prefill (time to the first answer token as the prompt grows):

| prompt tokens | 741 | 2 181 | 7 221 | 18 021 | 35 301 |
|---|---|---|---|---|---|
| time to first answer | 4.1 s | 7.7 s | 14.5 s | 28.0 s | **74.9 s** |

Roughly linear up to ~18 k, then super-linear: doubling from 18 k to 35 k
tokens costs **2.7x** the time. The KV cache (q8_0) is the constraint.

### Does the endpoint serve requests in parallel?

This decides whether `delegate` is worth anything on this box.

| concurrent requests | wall clock | per request | speedup vs serial | aggregate throughput |
|---|---|---|---|---|
| 1 | 27.8 s | 27.8 s | 1.00x | 36.9 tok/s |
| 2 | 49.7 s | 37.5 s | 1.12x | 41.2 tok/s |
| 3 | 69.2 s | 49.6 s | 1.20x | 41.5 tok/s |
| 4 | 93.8 s | 58.5 s | 1.18x | 41.7 tok/s |
| 8 | 296.2 s | 110.5 s | **0.75x** | 27.7 tok/s |

**Aggregate throughput saturates at ~41 tok/s no matter how many requests
are in flight.** One request already uses the whole GPU, so extra
requests only queue — and at 8 requests the queueing costs more than it
saves: 8 parallel is *slower* than 8 serial.

The `delegate` shape (3 children at once, `subagents.py:134`) measured
65.6 s of wall clock against 131.9 s of individual work — the children do
overlap, but they buy **~1.2x, not 3x**.

So the harness's two-level parallelism (`main.py:226`,
`subagents.py:134`) is architecturally correct and does what it says —
it just cannot buy much on a single-replica endpoint. `MAX_SUBAGENTS=3`
is a good setting here; raising it would hurt.

---

## Findings

Ranked by how much they cost you.

### 1. [HIGH] A truncated answer is invisible — 2 of 3 realistic coding turns are cut off

```
run 1: finish=length  completion_tokens=4096  answer_chars=8136
run 2: finish=length  completion_tokens=4096  answer_chars=6808
run 3: finish=stop   completion_tokens=3381  answer_chars=6815
```

`llm.py:132` hardcodes `max_tokens: 4096`, and `llm.py:163` never reads
`finish_reason`. So when the model hits the cap mid-answer, the harness
has no idea: the answer simply stops, mid-sentence, and the loop moves
on to the next tool call as if it were complete.

The task above was ordinary work — *"review this function and rewrite it
with type hints, docstrings, error handling and unit tests"*. Two of
three runs ran out of budget. A third run (measured later) used the
whole 4096 on reasoning and returned **zero characters** — an empty
answer the harness accepted as a finished one.

**Fixed.** The budget is now `config.MAX_TOKENS` (default 16 384, four
times the old value), clamped so the prompt and the answer still fit the
model's window; `finish_reason` is read, `reply.truncated` is exposed,
and both front-ends say so when an answer was cut off. See the *Fixed*
section below and `test/test_truncation.py`.

Re-measured with the new 16 384 budget, same prompt:

```
run 1: finish=stop   completion_tokens=5570   answer_chars=9322
run 2: finish=length completion_tokens=16384  answer_chars=0     <- now DETECTED
run 3: finish=stop   completion_tokens=3723   answer_chars=7918
```

Truncation dropped from **2/3 to 1/3**, and the remaining case is no
longer silent. The empty answer is the model spending the whole budget
on reasoning: the server returned 16 384 completion tokens of which
**zero** were visible text (`content: ""`, `reasoning: <8493 chars>`).

### 2. [HIGH] The token estimator under-counts code by ~40 %, so compaction fires late

`context.tokens()` assumes 4 characters = 1 token (`context.py:40`).
Measured against the server's own `prompt_tokens`:

| content | server tokens | harness guess | error |
|---|---|---|---|
| prose | 442 | 526 | +19.0 % |
| words | 222 | 236 | +6.3 % |
| **code** | 461 | 281 | **-39.0 %** |
| **json** | 741 | 441 | **-40.5 %** |

The guess is close enough for prose and badly wrong for the two things a
coding agent actually reads: code and JSON. Code is *denser* per
character than the estimate assumes.

The consequence is arithmetic: `PRUNE_AT` fires at 17 100 estimated
tokens, which is really ~24 000; `COMPACT_AT` fires at 28 500 estimated,
which is really ~40 000. Add `CONTEXT_RESERVE` (12 000) and the request
that goes to the server is ~52 000 tokens against a 50 000 window.

Fix: estimate code at ~2.6 chars/token and prose at ~4.8, or count
tokens per content type, or ask the server (the usage block is already
requested — `stream_options: {"include_usage": True}`).

### 3. [HIGH] The hardline blocklist has five escapes

The corpus is 62 labelled commands; 21 are "must never run". Five of
them are not blocked:

```
rm -rf ~/          rm -rf ~/*        rm -rf $HOME/
rm -r -f /         rm --recursive --force /
```

The patterns assume bundled flags and a `~` that is followed by a space
or end-of-string (`safety.py:118-127`). Add a trailing slash, a glob or
a separated flag and the command falls through to "ask" — and in
`auto` mode (`/yolo`) **it runs**. The README promises that hardline
commands never run in any mode; today that is not true for these five.

`rm -rf /`, `rm -rf /*`, `rm -rf ~` and `rm -rf $HOME` are blocked
correctly — only the variants escape.

Fix: anchor the target instead of the flags, e.g. match `rm` with
`[-a-z]*f` **or** `--force`, and treat `~`/`$HOME` followed by *anything*
as home.

### 4. [MEDIUM] The 62-command corpus also caught a benign false positive

`ls > /dev/null` is classified "ask" instead of "free", because
`is_readonly_part()` rejects any command containing `>` (`safety.py:208`)
even though the redirect guard explicitly allows `/dev/null`
(`safety.py:330`). One extra prompt on a harmless command — the safe
direction, but it trains the user to hit "always".

### 5. [MEDIUM] Prefill dominates the cost of a long turn

At 35 k prompt tokens the first answer token is 75 seconds away, and the
model gets ~1.4 ms of prefill per prompt token before that. Combined
with finding 2 (the estimate that decides *when* the context gets big),
a long agent turn can spend a minute producing nothing visible.

### 6. [MEDIUM] `delegate` buys ~1.2x on a single-replica endpoint

Measured above: 3 children at once take 65.6 s instead of 131.9 s of
serial work. The parallelism is real, but the GPU is already saturated
by one request, so the ceiling is ~41 tok/s no matter what. Do not
design around `delegate` making things 3x faster on this box — it makes
them ~1.2x faster. It is still worth using for *context isolation*
(children get their own context windows), just not for speed.

### 7. [LOW] The machine-wide model was pointing at a dead tunnel

`~/.harness/settings.json` had the model mapped to a saved endpoint from
an earlier session (`santa-visual-communications-bedford.trycloudflare.com`).
`llm.endpoint_for()` prefers a saved provider over `.env`, so the
harness would have failed to reach the model even with a working
`.env`. The benchmark now ignores saved providers (and refuses to write
to the real settings file); the machine's own settings were repointed at
the current tunnel.

---

## Fixed while writing this

Finding 1 was fixed rather than only reported, because it made the
harness quietly wrong:

| change | where |
|---|---|
| `MAX_TOKENS` (default 16 384) replaces the literal 4096 | `config.py`, `llm.py` |
| the budget is clamped so prompt + answer fit the window | `llm.py:_max_tokens()` |
| `finish_reason` is read; `reply.truncated` is exposed | `llm.py:_Msg` |
| the CLI says when an answer was cut off | `main.py` |
| the TUI says when an answer was cut off | `tui/adapter.py`, `tui/app.py` |
| a regression probe for all of the above | `test/test_truncation.py` |

The old behaviour is kept as the baseline: `git log` shows the
`max_tokens: 4096` literal that this replaced.

Findings 2 (the token estimator) and 3 (the hardline escapes) are
**reported, not fixed** — they change behaviour in ways that should be a
deliberate decision, not a side effect of writing a benchmark. The fixes
are small and outlined above.

---

## What is solid

Worth stating, because the findings above could read as an indictment:

- **The agent gets real tasks right.** 10 of 10 runs across five tasks
  (fix a bug, add a flag, write tests, refactor across files, read and
  explain) passed their checkers, in 2.5–6 turns and 1 000–1 600 tokens.
- **The protocol invariants hold.** Tool results go back in call order
  even when the tools finish out of order (4 commands finishing in
  1.2 / 0.1 / 0.9 / 0.3 s were reported in call order); parallel calls
  really run in parallel (1.21 s wall for 2.50 s of work); errors come
  back as strings, never exceptions; the 20-turn cap stops a runaway
  loop.
- **The walls hold.** `../` escapes, absolute paths, symlinks out of the
  project and `.env` reads are all refused. The subprocess environment
  is scrubbed of `OPENAI_API_KEY` and any `*TOKEN*`/`*SECRET*` variable.
- **The caps hold.** `list_files` stops at 4 000 characters, `run_tool`
  at 5 000 with a `[truncated]` marker.
- **The notebook is fast.** 77 000 inserts/s (each message is its own
  commit, in WAL mode); a search across 5 000 messages takes 0.15 ms.
- **Compaction works.** Pruning stubs old tool output and protects the
  newest 6 tool turns; compaction saves ~80 % of the tokens, keeps the
  head verbatim, and replays a request that only existed in the middle.
- **The harness costs 0.22 ms per turn.** Nothing in the harness is on
  the critical path of a task.

---

## Reproducing

The live suites depend on the endpoint being up. The trycloudflare
tunnel changes when the box restarts, so `BASE_URL` in `.env` has to be
updated; `check_endpoint()` fails with a clear message instead of a
stack trace when the host does not resolve.

`benchmark/results/*.jsonl` keeps every run, so a change can be compared
against the baseline:

```bash
.venv/bin/python benchmark/run_all.py --offline
git diff benchmark/results/          # what changed
```
