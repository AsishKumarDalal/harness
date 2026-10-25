<p align="center">
  <img src="assets/harness.svg" alt="The Harness logo" width="96" height="96">
</p>

<h1 align="center">The Harness</h1>

<p align="center">
  <strong>A small, complete agentic coding CLI</strong> — Claude Code shape, Python body.<br>
  ~2600 lines of core, ~2100 more for the Textual TUI, one OpenAI-compatible model
  endpoint. Built phase by phase with Hermes-agent as the reference design.
</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white">
  <img alt="License" src="https://img.shields.io/badge/License-Personal%20%2F%20Learning-lightgrey">
  <img alt="Status" src="https://img.shields.io/badge/Status-Experimental-orange">
</p>

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
- **Web tools**: `web_search` (DuckDuckGo via `ddgs`, no API key) and
  `web_fetch` (a page as plain text; a GitHub blob URL becomes the raw file) —
  local and private addresses are refused
- **Safety gate** — tiered approvals (reads free, writes/exec ask), persistent
  allow rules, hardline blocklist, secret/redirect/env guards, and
  `ask` / `auto` / `plan` modes
- **Two-tier context management** — prune old tool output at 45%, LLM-summarize
  the middle at 75%, archive (never delete) so nothing is truly lost
- **Persistent sessions** — SQLite notebook, write-through, crash-resume,
  `/resume`, `/search` across all sessions incl. subagent transcripts
- **Skills** — `SKILL.md` folders the model loads on demand, machine-wide or
  per project, the way Claude Code does it
- **Textual TUI** (`harness-tui`) — an opencode-style front-end over the same
  core: streaming answers, tool blocks, coloured diffs, inline approvals, a
  command palette and a `/model` window; the view never jumps while an answer
  streams in
- **The model is a machine-wide choice** — `/model` follows you from project to
  project, and a model can be added from any endpoint (base url + api key)
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

Both paths need **Python 3.11+**; the npm path also needs **Node 18+**.

### npm (recommended)

```bash
git clone https://github.com/AsishKumarDalal/harness.git && cd harness
npm install -g .
```

That puts **`harness`** and **`harness-tui`** on your PATH. The first launch
creates a private Python environment in `~/.harness/venv`, installs the
dependencies, and copies `.env.example` to `~/.harness/.env` — edit that file
once (API key, `BASE_URL`, `MODEL`). That first launch needs an internet
connection so `pip` can download the Python packages.

The npm package deliberately has no install scripts (newer npm versions block
them by default), so the Python setup runs on first launch instead. After a
`git pull`, the launcher notices a changed `requirements.txt` and installs the
new dependencies by itself.

```bash
cd ~/projects/my-app
harness --version
harness
```

To remove the commands again: `npm uninstall -g the-harness`. Your sessions and
settings stay in `~/.harness` (delete that folder too if you want them gone).

> Upgrading from `./install.sh`? Its `~/.local/bin/harness` symlinks can shadow
> npm's commands. Remove the two old symlinks, or make sure npm's global `bin`
> folder comes first on your PATH (`npm prefix -g`).

### Without npm

On a **fresh machine** (one command does everything — venv, deps, PATH, `.env`):

```bash
git clone https://github.com/AsishKumarDalal/harness.git && cd harness
./install.sh
```

`install.sh` creates `.venv`, installs `openai` + `python-dotenv` + `textual` +
`ddgs`, links **`harness`** and **`harness-tui`** into `~/.local/bin` (already on
your PATH), and copies `.env.example` → `.env`. Edit `.env` (API key, `BASE_URL`,
`MODEL`).

By hand, if you prefer:

```bash
git clone https://github.com/AsishKumarDalal/harness.git && cd harness
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt   # openai, python-dotenv, textual, ddgs
cp .env.example .env                        # then edit it
ln -s "$(pwd)/harness" ~/.local/bin/harness # ~/.local/bin is already on PATH
ln -s "$(pwd)/harness-tui" ~/.local/bin/harness-tui
```

Then, in **any** project folder:

```bash
cd ~/projects/my-app
harness                     # starts the agent on the folder you are in
harness ~/projects/other    # ...or on another folder
harness -m gpt-4o-mini      # ...with another model
harness-tui                 # ...the same agent, in the Textual TUI
```

`harness` is a thin launcher: it runs the CLI with the Python environment, keeps
your current folder as the project, and keeps every file of its own out of it.

`.env` (the npm launcher writes `~/.harness/.env`; a clone-local `.env` wins if
both exist):

```
OPENAI_API_KEY=ollama                  # server ignores it; SDK requires one
BASE_URL=https://<tunnel>.trycloudflare.com/v1   # any OpenAI-compatible endpoint
MODEL=k2-horizon-mova-36b-a4b
```

All settings live in `config.py` and are overridable in `.env` (`CONTEXT_LIMIT`,
`MAX_SUBAGENTS`, `MAX_SPAWN_DEPTH`, …).

The **model** you pick in the app (`/model`) is saved in
`$HARNESS_HOME/settings.json` and follows you from project to project — a new
project does not mean a new model choice. A model can also be added from any
other endpoint (base url + api key) — see "The model is a machine-wide choice"
below.

> If you run the checkout by hand, `python`/`python3` are not on PATH in this
> environment — always use `.venv/bin/python` (the launcher scripts do that for
> you).

## Terminal UI (Textual)

The same agent, with an opencode-style terminal front-end: dark, chat-centred,
keyboard-first.

```bash
cd ~/projects/my-app
.venv/bin/python -m tui            # the folder you are in is the project
.venv/bin/python -m tui ~/other    # ...or another folder
.venv/bin/python -m tui -m gpt-4o  # ...with another model
```

After `npm install -g .` (or `./install.sh`) there is also a `harness-tui`
command, same idea as `harness`:

```bash
cd ~/projects/my-app
harness-tui
```

| Key | What it does |
|---|---|
| `enter` | send |
| `shift+enter` | new line in the prompt |
| `esc` | interrupt the running generation |
| `ctrl+p` | command palette — switch session or model |
| `ctrl+c` | quit |

Slash commands: `/new [title]`, `/sessions`, `/resume <id\|title>`, `/model`,
`/skills`, `/clear`, `/help`. `/model` opens a window (see below), everything
else answers in the chat.

What you get:

- **streaming** — the answer appears live in a markdown block; the UI never blocks
- **a view that stays put** — the chat is *anchored* to the bottom, so a long
  answer grows downwards instead of pushing the text around; scroll up to read
  something and the follow stops until you scroll back
- **project instructions** — an `AGENT.md` in the **project** folder (never the
  harness' own) becomes the system prompt; the top bar shows a green
  `AGENT.md` badge and the chat says where it was loaded from
- **tool calls** — one compact block per call: name, arguments, status dot
  (running / done / failed / denied) and the output; click to expand
- **diffs** — file edits are snapshotted before and after the call and shown as a
  coloured diff (green added, red removed)
- **approvals** — shell commands and file writes ask first: `y` once,
  `a` always allow, `n` deny (same policy as the CLI)
- **sessions** — `/sessions` and the palette list the stored sessions; picking one
  replays its transcript

The harness core is untouched: the UI drives it through `tui/adapter.py`, which
runs the agent loop in a worker thread and turns its activity into small events.
The one change to the core is an optional `stop` hook on `llm.chat()` so a
generation can be interrupted.

Every colour lives in `tui/app.tcss` as a variable — edit those ten lines to
re-theme the whole app.

## Your project stays clean

The harness keeps **its own files outside the project it works on** — the same
way opencode keeps its data in `~/.local/share/opencode`:

| What | Where | Override |
|---|---|---|
| session notebook (`state.db`), safety rules (`safety.json`), `/export` JSONL | `~/.harness/` | `HARNESS_HOME` env (or `.env`) |
| the model, the saved endpoints (`settings.json`, mode 600) | `~/.harness/` | `HARNESS_HOME` env (or `.env`) |
| machine-wide skills (`<name>/SKILL.md`) | `~/.harness/skills/` | `HARNESS_HOME` env (or `.env`) |
| Python environment for an npm install | `~/.harness/venv/` | `HARNESS_HOME` env |
| project skills (`<name>/SKILL.md`) | `<project>/.harness/skills/` | — (this one *is* meant to be committed) |
| the project the agent reads/writes | the folder you run `harness` in, `--project <dir>`, `PROJECT_DIR` env | — |

So `harness` never drops a `.harness/`, a `__pycache__/`, or a database into
your project — the only files that appear there are the ones the agent was
asked to create or edit. A v1 `<harness>/.harness` folder is migrated into
`HARNESS_HOME` automatically on the first run.

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
| `/model [name\|add]` | show the model, set it **for this machine**, or add one from another endpoint |
| `/skills` | list the skills that can be loaded |
| `/mode [ask\|auto\|plan]` | show/change the safety mode |
| `/safety` | show mode, allow rules, tool tiers |
| `/allow <rule>` | add a persistent rule (`bash:<glob>` / `tool:<name>`) |
| `/unallow <rule>` | remove a persistent rule |
| `/yolo` | toggle auto mode |
| `exit` / `quit` | end session and quit |

Anything else is sent to the agent.

## The model is a machine-wide choice

`/model` (in the CLI and in the TUI) sets the model for **this machine**, not for
one project:

```
/model                 -> model: k2-horizon-mova-36b-a4b   (saved, machine-wide)
/model gpt-4o-mini     -> model set to gpt-4o-mini (saved for this machine)
```

The choice is kept in `$HARNESS_HOME/settings.json`, so it follows you from
project to project — set it once, every later run uses it. `harness -m <name>`
is the per-run override (it does not stick).

In the TUI, `/model` opens a small window instead: it shows the model in use
right now, the models this machine knows (the current one, `$MODELS` and the
ones used in earlier sessions) and an input where you can type any new model
name and press enter. `tab` moves to the list, `esc` closes the window without
changing anything.

### Adding a model from another endpoint

The first entry of that window is **＋ add a new model**. It asks for the
**base url** and the **api key**, then reads the model list from that
endpoint and asks which one to use:

```
base url (e.g. https://api.openai.com/v1)   →  https://api.openai.com/v1
api key                                     →  sk-...
which model do you want?                    →  gpt-4o
```

The endpoint is remembered in `$HARNESS_HOME/settings.json` (mode 600 — it
holds the key) and the chosen model talks to *that* endpoint from then on, in
every project. Models without a saved endpoint keep using the `.env`
`BASE_URL` / `OPENAI_API_KEY`. The CLI has the same flow: `/model add`.

## Skills (the Claude Code way)

A skill is a folder with a `SKILL.md` — a named set of instructions the model
can load when the task fits it:

```
~/.harness/skills/pdf/SKILL.md            this machine, every project
<project>/.harness/skills/pdf/SKILL.md    this project only
```

```markdown
---
name: pdf
description: Extract text and tables from PDF files
---

# Working with PDFs

Use `pdftotext` for the text, `pdfimages` for the pictures …
```

The model is told which skills exist (name + description) in its system
prompt and loads the full instructions on demand with the `skill` tool — so a
skill costs nothing until it is really needed. `/skills` lists them. A project
skill with the same name wins over a machine one.

## The docs

One document per phase — the problem, the mechanism, the design choices, and
what was actually verified:

| Doc | Phase | What it covers |
|---|---|---|
| [phase_1](docs/phase_1.md) | Foundation | venv, `.env`, config / llm / messages / minimal loop |
| [phase_2](docs/phase_2.md) | Agent loop + tool calling | `SCHEMA`, `REGISTRY`, `run_tool`, error recovery |
| [phase_3](docs/phase_3.md) | Real coding tools | path jail, output caps, search, shell |
| [phase_4](docs/phase_4.md) | Safety gate | tiers, modes, hardline, rules, guards |
| [phase_5](docs/phase_5.md) | Context management | prune @ 45 %, LLM summary @ 75 %, archive-not-delete |
| [phase_6](docs/phase_6.md) | Sessions | SQLite notebook, write-through, resume, search |
| [phase_7](docs/phase_7.md) | Streaming UI + thinking | OpenCode-style renderer, `delta.reasoning` routing |
| [phase_8](docs/phase_8.md) | Subagents + parallel calls | `delegate`, two-level parallelism |
| [phase_9](docs/phase_9.md) | Skills | `SKILL.md` folders, catalogue in the prompt, `skill` tool |

## Project layout

```
package.json          npm package: `npm install -g .`, bin entries
bin/                   the npm launchers (Node -> Python, cwd preserved)
scripts/               first-run Python venv bootstrap + process launcher
cli.py           60   the `harness` command: arg parsing, project selection
harness          28   launcher script (put it on your PATH)
harness-tui      28   launcher for the Textual front-end
install.sh       92   one-command setup for a fresh machine (no Node needed)
config.py       230   all settings, read from .env
safety.py      477   permission gate: tiers, modes, hardline, guards
web.py         244   the internet tools: ddgs search + safe page fetch
skills.py      150   loadable instruction sets (Claude Code style)
llm.py         189   the ONLY file that talks to the model (streaming, thinking)
messages.py     58   Conversation — write-through live memory
tools.py       277   tool registry + runner + schemas
main.py        374   agent loop, REPL, streaming UI
context.py     189   two-tier compaction
sessions.py    235   SQLite notebook (the archive)
subagents.py   153   parallel child agents (delegate)
tui/            2.1k the Textual front-end (app, adapter, widgets, screens, theme)
docs/                 one detailed doc per phase (Mermaid diagrams)
test/                 offline probes (safety, web, TUI, model, skills)
```

> The harness' own state lives in `~/.harness/` (or `$HARNESS_HOME`), never in
> the project folder — see "Your project stays clean" above.

## Tests

Everything is an offline probe — no model server needed:

```bash
.venv/bin/python test/test_safety.py        # 39  the permission gate
.venv/bin/python test/test_web.py           # 26  the internet tools + SSRF guards
.venv/bin/python test/test_tui_commands.py  # 25  slash commands, palette, sessions
.venv/bin/python test/test_tui_layout.py    #  8  wrapping, never cut at the right
.venv/bin/python test/test_tui_agent_md.py  #  6  the project's AGENT.md
.venv/bin/python test/test_tui_scroll.py    #  9  the view never jumps while streaming
.venv/bin/python test/test_tui_stream.py    #  5  a streamed answer reads like a finished one
.venv/bin/python test/test_model_skills.py  # 47  the machine-wide model, endpoints, skills
```

The last two are regression tests: they fail on the code before the fix (98
lines painted above the end of the chat; a 61 ms flush instead of 2 ms).

## How it works (30 seconds)

1. You type a message → `agent()` adds it, runs `maybe_compact()` (no-op
   until 45 % full), calls `chat()` with `SCHEMA`, streams the reply through
   the markdown renderer while routing `delta.reasoning` to the thinking block.
2. If the reply has `tool_calls`, `safety.gate_one()` classifies each call
   (free / ask / denied) **before** dispatch — prompts run on the main thread.
   Approved calls run in a `ThreadPoolExecutor`, each result capped at
   4000/5000 chars, then `convo.add_tool(id, result)` in **call order**
   (protocol invariant). Denials go back as ordinary tool results.
3. Loop repeats until the model answers without tools or hits 20 turns.
4. `Conversation` writes through to SQLite on every add; compaction later
   marks rows `active=0` — **archived, not deleted** — so `/search` and
   `session_search` still find them.
5. `delegate` spawns N children in threads; each gets a fresh `Conversation`,
   its own session row with `parent_session_id`, tools minus `delegate`, and
   returns a trimmed summary. Results are one consolidated block per call.

In the TUI the same loop runs in a worker thread and reports small events
(`Token`, `ToolCall`, `ApprovalNeeded`, …) that the app renders. Two details
make the streaming feel solid: the answer is **appended** to the markdown block
instead of being rebuilt (a flush costs the same at 1000 lines as at 10), and
the chat is **anchored** to the bottom, so the compositor pins the view while
the content grows — the text never jumps.

See [docs/README.md](docs/README.md) and [docs/phase_1.md](docs/phase_1.md) for
the full design walkthrough (9 phases, a diagram for every mechanism —
including [phase 9: skills](docs/phase_9.md)).

## Safety

Implemented in `safety.py` (Claude Code + Hermes style):

- **Modes** — `ask` (default), `auto`, `plan` (read-only). Switch with `/mode`
  or `/yolo`. Rules and mode persist in `$HARNESS_HOME/safety.json`
  (default `~/.harness/safety.json`).
- **Hardline blocklist** — `rm -rf /`, fork bombs, raw disk writes, `curl | sh`,
  shutdown commands are refused always, even in `auto` mode.
- **Read-only shell** — `ls`, `cat`, `grep`, `git status`, and read-only
  compounds run without prompts. Compound commands are split, so
  `git status && rm -rf build` still asks.
- **Approval prompt** — `write_file`, `edit_file`, `run_command`, `delegate`,
  `web_fetch`: `[y] once / [a] always / [n] no` (default deny). "Always" saves
  rules. `web_search` is a plain read and never asks.
- **Web guard** — `web_fetch` only speaks http(s) and refuses addresses that
  point back at the machine (`localhost`, `10.x`, `192.168.x`, `169.254.169.254`,
  `::1`), the host is re-checked after DNS, and every redirect is checked too.
- **Guards** — path jail (`_safe` uses `relative_to`), secret-file refusal
  (reads, writes, `cat .env`), redirect/`tee` targets outside the project,
  credential-free subprocess env (`OPENAI_API_KEY` etc. are stripped).
- **Honest limit** — these are app-level checks: they stop accidents, not a
  determined attacker. For real isolation run the agent in a container or
  under an OS sandbox (bubblewrap, Docker, VM).

## License

Personal/learning project. No warranty. Use at your own risk.
