# The Harness

A small, complete **agentic coding CLI** — think "Claude Code shape, Python body."
~1300 lines, stdlib-first, one OpenAI-compatible model endpoint. Built phase
by phase with [Hermes-agent] as the reference design.

```text
you > refactor the login flow to use sessions instead of cookies
assistant
  thinking...  (dim/italic reasoning block, then ───)
  ├─ read_file({"path":"src/auth.py"})
  └─ ...file contents...
  ├─ delegate({"tasks":[
       {"goal":"map the auth-related files","context":"..."},
       {"goal":"find all cookie usages","context":"..."}]})
  └─ [2 subagent(s) finished]
  ...synthesized answer...
  model │ ctx 12345/38000 (32%) │ in:9000 out:400
```

## Features

- **Agent loop** with tool calling, 20-turn cap, automatic error recovery
  (errors go back to the model as strings, never crashes)
- **Coding tools**: `list_files`, `read_file`, `write_file`, `edit_file`,
  `search_files`, `run_command` — path-jail, output caps, secret-file refusal
- **Two-tier context management** — prune old tool output at 45%, LLM-summarize
  the middle at 75%, archive (never delete) so nothing is truly lost
- **Persistent sessions** — SQLite notebook, write-through, crash-resume,
  `/resume`, `/search` across all sessions incl. subagent transcripts
- **Streaming OpenCode-style UI** — line-buffered markdown, boxed code fences,
  tool tree (`├─`/`└─`), status line, hidden "thinking..." indicator
- **Thinking tokens** — `delta.reasoning` routed to a dim/italic block, never
  stored in history
- **Parallel subagents** via `delegate` — children run in threads with their own
  context windows and their own sessions; `MAX_SUBAGENTS=3` per batch; multiple
  batches in one turn run side by side
- **Parallel tool execution** — every tool call in one assistant turn runs
  concurrently, results returned in call order
- **Cross-session memory** — `session_search` tool lets the model (and you)
  grep everything ever stored

## Quick start

```bash
git clone <this-repo> the-harness && cd the-harness
python -m venv .venv
.venv/bin/pip install -r requirements.txt   # openai, python-dotenv
cp .env.example .env                        # then edit it
.venv/bin/python main.py
```

`.env`:

```
OPENAI_API_KEY=ollama                  # server ignores it; SDK requires one
BASE_URL=https://<tunnel>.trycloudflare.com/v1   # any OpenAI-compatible endpoint
MODEL=k2-horizon-mova-36b-a4b
```

All settings live in `config.py` and are overridable in `.env` (`CONTEXT_LIMIT`,
`MAX_SUBAGENTS`, `MAX_SPAWN_DEPTH`, …).

> `python`/`python3` are not on PATH in this environment — always use
> `.venv/bin/python`.

## REPL commands

| Command | What it does |
|---|---|
| `/new [title]` | start a fresh session |
| `/sessions` | list sessions (id, title, message count, end reason) |
| `/resume <id\|title>` | load a session, show recap, warn if interrupted mid-turn |
| `/title <t>` | rename current session |
| `/export` | dump the whole session (live + archived) to JSONL |
| `/prune` | delete finished sessions older than 30 days |
| `/search <q>` | grep every message ever stored |
| `exit` / `quit` | end session and quit |

Anything else is sent to the agent.

## Project layout

```
config.py       42   all settings, read from .env
llm.py         151   the ONLY file that talks to the model (streaming, thinking)
messages.py     51   Conversation — write-through live memory
tools.py       224   tool registry + runner + schemas
main.py        269   agent loop, REPL, streaming UI
context.py     189   two-tier compaction
sessions.py    235   SQLite notebook (the archive)
subagents.py   153   parallel child agents (delegate)
docs/                 one detailed doc per phase (22 Mermaid diagrams)
test/                 throwaway probes (one behavior each, real server)
.harness/             state.db lives here (gitignored)
```

## How it works (30 seconds)

1. You type a message → `agent()` adds it, runs `maybe_compact()` (no-op
   until 45 % full), calls `chat()` with `SCHEMA`, streams the reply through
   the markdown renderer while routing `delta.reasoning` to the thinking block.
2. If the reply has `tool_calls`, they run in a `ThreadPoolExecutor`, each
   result capped at 4000/5000 chars, then `convo.add_tool(id, result)` in
   **call order** (protocol invariant).
3. Loop repeats until the model answers without tools or hits 20 turns.
4. `Conversation` writes through to SQLite on every add; compaction later
   marks rows `active=0` — **archived, not deleted** — so `/search` and
   `session_search` still find them.
5. `delegate` spawns N children in threads; each gets a fresh `Conversation`,
   its own session row with `parent_session_id`, tools minus `delegate`, and
   returns a trimmed summary. Results are one consolidated block per call.

See [docs/README.md](docs/README.md) and [docs/phase_1.md](docs/phase_1.md) for
the full design walkthrough (8 phases, ~1600 lines, diagrams for every
mechanism).

## Safety status (read this)

This harness is **deliberately not gated**: `write_file`, `edit_file`,
`run_command`, and `delegate` execute without approval. The only protections
today are the project path jail (`_safe()`), secret-file refusal, a 60-second
shell timeout, and output caps — these stop *accidents*, not *misuse*. Approval
gating is designed (see [docs/phase_4.md](docs/phase_4.md)) but not wired yet.
Run it on code you own.

## License

Personal/learning project. No warranty. Use at your own risk.
