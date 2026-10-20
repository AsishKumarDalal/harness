"""main.py — the REPL. Streams like OpenCode: markdown, tool tree, status line."""

import concurrent.futures
import re

import config
import sessions
from context import history_tokens, maybe_compact
from llm import _last_usage, chat
from messages import Conversation, default_system_prompt
from tools import SCHEMA, run_tool

# ---------- colour palette (OpenCode-ish) ----------
C = "\033[36m"      # cyan   - assistant / code
D = "\033[2m"       # dim    - meta / tools
B = "\033[1m"       # bold
G = "\033[32m"      # green  - ok / prompt
M = "\033[35m"      # magenta- headings
R = "\033[0m"       # reset

MAX_TURNS = 20
convo = None


# ---------- tiny markdown renderer (line based, streams) ----------
def _inline(s: str) -> str:
    s = re.sub(r"`([^`]+)`", lambda m: f"{C}{m.group(1)}{R}", s)
    s = re.sub(r"\*\*([^*]+)\*\*", lambda m: f"{B}{m.group(1)}{R}", s)
    s = re.sub(r"\*([^*]+)\*", lambda m: f"\033[3m{m.group(1)}{R}", s)
    return s


def _render_line(line: str, st: dict):
    if line.startswith("```"):
        if not st["in_code"]:
            st["in_code"] = True
            st["lang"] = line[3:].strip()
            label = st["lang"] or "code"
            return f"{D}┌─ {label}{R}", st
        st["in_code"] = False
        return f"{D}└─{R}", st
    if st["in_code"]:
        return f"{D}│{R} {C}{line}{R}", st
    s = line
    if s.startswith("# "):
        return f"{M}{B}{s[2:]}{R}", st
    if s.startswith("## "):
        return f"{B}{s[3:]}{R}", st
    if s.startswith("- ") or s.startswith("* "):
        return f"  {G}•{R} {_inline(s[2:])}", st
    if s.startswith("> "):
        return f"{D}│ {_inline(s[2:])}{R}", st
    if s.strip() in ("---", "***", "___"):
        return f"{D}{'─' * 40}{R}", st
    return _inline(s), st


class MDStream:
    """Streams markdown to the terminal as tokens arrive."""

    def __init__(self):
        self.buf = ""
        self.st = {"in_code": False, "lang": ""}

    def write(self, chunk: str):
        self.buf += chunk
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            styled, self.st = _render_line(line, self.st)
            print(styled, flush=True)

    def flush(self):
        if self.buf:
            styled, self.st = _render_line(self.buf, self.st)
            print(styled, flush=True)
            self.buf = ""
        if self.st.get("in_code"):
            print(f"{D}└─{R}", flush=True)
            self.st["in_code"] = False
        print(flush=True)


# ---------- app ----------
def banner():
    print(f"{C}{B}opencode{R}  {D}python harness{R}")
    print(f"{D}model: {config.MODEL}   cwd: {config.START_DIR}{R}")
    print(f"{D}context: {config.CONTEXT_LIMIT} tokens   (prune@{int(config.PRUNE_AT*100)}% compact@{int(config.COMPACT_AT*100)}%){R}")
    print(f"{D}{'─' * 60}{R}")


def new_session(title=None):
    global convo
    sid = sessions.new_session(title, default_system_prompt(),
                               config.MODEL, str(config.START_DIR))
    convo = Conversation(default_system_prompt(), sid)
    sessions.set_current(sid)
    print(f"{D}new session: {sid}{R}")


def show_recap(history):
    print(f"{D}--- previous conversation ---{R}")
    for m in history[-20:]:
        text = (m.get("content") or "").strip()
        if m.get("role") == "user":
            print(f"  {G}you:{R} {text[:300]}")
        elif m.get("role") == "assistant":
            if m.get("tool_calls"):
                names = ", ".join((tc.get("function") or {}).get("name", "?")
                                  for tc in m["tool_calls"])
                print(f"   {D}[tools: {names}]{R}")
            if text:
                print(f"  {C}agent:{R} {text[:200]}")
    print(f"{D}---------------------------{R}")


def resume(key):
    global convo
    row = sessions.find_session(key)
    if not row:
        print(f"no session matching '{key}'")
        return
    history = sessions.load_messages(row["id"])
    if not history:
        print("that session has no messages")
        return
    system = history[0]["content"] if history[0].get("role") == "system" else default_system_prompt()
    convo = Conversation(system, row["id"])
    convo.history = history
    sessions.set_current(row["id"])
    sessions.reopen_session(row["id"])
    print(f"resumed {row['id']}  ({row.get('title') or 'untitled'})")
    if row.get("model") and row["model"] != config.MODEL:
        print(f"{D}note: that session used {row['model']}, current model is {config.MODEL}{R}")
    show_recap(history)
    if history and history[-1].get("role") == "user":
        print(f"{D}! last turn was interrupted (no answer stored) — send it again to retry{R}")


def status_line():
    toks = history_tokens(convo.history)
    pct = int(100 * toks / config.CONTEXT_BUDGET) if config.CONTEXT_BUDGET else 0
    u = _last_usage
    print(f"{D}  {config.MODEL}  │  ctx {toks}/{config.CONTEXT_BUDGET} ({pct}%)  │  "
          f"in:{u.get('prompt_tokens', 0)} out:{u.get('completion_tokens', 0)}{R}")


def agent(user_msg: str) -> str:
    convo.add_user(user_msg)
    sessions.auto_title(convo.session_id, user_msg.strip().splitlines()[0][:60])
    for _ in range(MAX_TURNS):
        new_hist = maybe_compact(convo.history)
        if new_hist is not convo.history:
            convo.history[:] = new_hist
            convo.sync()
        print(f"\n{C}{B}assistant{R}")
        print(f"{D}  thinking...{R}", end="", flush=True)
        printer = MDStream()
        state = {"cleared": False, "thinking": False, "answering": False}

        def first_output():
            if not state["cleared"]:
                print("\r\033[2K", end="", flush=True)
                state["cleared"] = True

        def on_thinking(piece):
            first_output()
            if not state["thinking"]:
                print(f"\033[2m\033[3mthinking: ", end="", flush=True)
                state["thinking"] = True
            print(piece, end="", flush=True)

        def on_token(piece):
            first_output()
            if state["thinking"] and not state["answering"]:
                print(f"{R}\n{D}{'─' * 40}{R}", flush=True)   # end thinking block
            state["answering"] = True
            printer.write(piece)

        reply = chat(convo.history, tools=SCHEMA,
                     on_token=on_token, on_thinking=on_thinking)
        if state["thinking"] and not state["answering"]:
            print(f"{R}", flush=True)                         # reset dim/italic
        printer.flush()
        convo.add_assistant(reply)
        if reply.tool_calls:
            calls = reply.tool_calls
            for tool in calls:                 # show every call BEFORE running
                args = (tool.function.arguments or "").strip()
                print(f"  {D}├─ {tool.function.name}({args[:100]}){R}", flush=True)
            results: dict = {}
            if len(calls) == 1:
                results[0] = run_tool(calls[0])
                preview = (results[0] or "").replace("\n", " ")[:120]
                print(f"  {D}└─ {preview}{R}", flush=True)
            else:
                # the agent asked for several tools at once -> run them ALL in
                # parallel (e.g. 2 delegate calls = 6 children racing together)
                with concurrent.futures.ThreadPoolExecutor(max_workers=len(calls)) as pool:
                    futures = {pool.submit(run_tool, t): i
                               for i, t in enumerate(calls)}
                    for fut in concurrent.futures.as_completed(futures):
                        i = futures[fut]
                        results[i] = fut.result()
                        preview = (results[i] or "").replace("\n", " ")[:120]
                        print(f"  {D}└─ [{i + 1}/{len(calls)}] {preview}{R}", flush=True)
            for i, tool in enumerate(calls):   # results go back in CALL order
                convo.add_tool(tool.id, results[i])
        else:
            status_line()
            return reply.content or ""
    status_line()
    return f"(stopped after {MAX_TURNS} tool turns)"


def handle_command(text: str):
    parts = text[1:].split(" ", 1)
    name = parts[0]
    arg = parts[1].strip() if len(parts) > 1 else ""

    if name == "new":
        new_session(arg or None)
    elif name == "sessions":
        rows = sessions.list_sessions()
        if not rows:
            print("(no sessions yet)")
        for r in rows:
            print(f"{r['id']}  {(r['title'] or 'untitled')[:38]:38}  {r['n']:>4} msgs  "
                  f"{r['end_reason'] or 'live'}")
    elif name == "resume":
        resume(arg)
    elif name == "title":
        sessions.set_title(convo.session_id, arg)
        print("title set")
    elif name == "export":
        print("exported ->", sessions.export_session(convo.session_id))
    elif name == "prune":
        n = sessions.prune_sessions(days=30, keep=convo.session_id)
        print(f"pruned {n} old session(s)")
    elif name == "search":
        hits = sessions.search(arg)
        if not hits:
            print("(no matches)")
        for h in hits:
            print(f"[{h['session_id']} {h['role']}] {(h['content'] or '')[:160]}")
    else:
        print("unknown command")


def main():
    banner()
    new_session()
    print(f"{D}commands: /new /sessions /resume <id|title> /title <t> /export /prune /search <q> | exit{R}")
    while True:
        try:
            user = input(f"\n{G}you >{R} ").strip()
        except (KeyboardInterrupt, EOFError):
            break
        if not user:
            continue
        if user in ("exit", "quit"):
            break
        if user.startswith("/"):
            handle_command(user)
            continue
        agent(user)
    sessions.end_session(convo.session_id)


if __name__ == "__main__":
    main()