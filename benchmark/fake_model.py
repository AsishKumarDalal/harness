"""benchmark/fake_model.py — a scripted, offline stand-in for the model server.

Why this exists
---------------
`llm.py` is the only file that talks to the model (docs/README.md:40). It
does exactly one thing:

    stream = client(model).chat.completions.create(**kwargs)
    for chunk in stream: ...          # llm.py:139-181

So replacing that one object with a script makes the WHOLE harness run
offline, deterministically and in milliseconds. That is what makes the
Tier-A suites (safety, tools, context, sessions, loop overhead)
reproducible enough to run in CI.

Two important details
---------------------
1. The chunk shape must match llm.py exactly:
      delta.content, delta.reasoning_content,
      delta.tool_calls[i].{index, id, function.name, function.arguments}

2. `main.py:13` and `context.py:23` do `from llm import chat` — patching
   `llm.chat` does NOT reach them. You must patch the *importing* module's
   binding: `main.chat` and `context.chat`. `install()` does all three.

Usage
-----
    from fake_model import Script, install
    install(Script([
        [("c", "let me look"), TC("read_file", '{"path": "hello.py"}')],
        [("c", "done")],
    ]))
"""

import types
from dataclasses import dataclass, field

import llm


# ---------------------------------------------------------------------------
# the wire shapes
# ---------------------------------------------------------------------------

class Delta:
    def __init__(self, content=None, reasoning=None, tool_calls=None):
        self.content = content
        self.reasoning_content = reasoning
        self.reasoning = reasoning
        self.tool_calls = tool_calls


class Choice:
    def __init__(self, delta):
        self.delta = delta
        self.finish_reason = None


class Usage:
    def __init__(self, prompt_tokens=0, completion_tokens=0):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = prompt_tokens + completion_tokens


class Chunk:
    def __init__(self, delta, usage=None, finish_reason=None):
        self.choices = [Choice(delta)]
        self.choices[0].finish_reason = finish_reason
        self.usage = usage


class Fn:
    def __init__(self, name="", arguments=""):
        self.name = name
        self.arguments = arguments


class TC:
    """A tool call to emit on the stream."""

    def __init__(self, name, arguments, index=0, call_id=None):
        self.name = name
        self.arguments = arguments
        self.index = index
        self.id = call_id or f"call_{name}_{index}"


# ---------------------------------------------------------------------------
# the script
# ---------------------------------------------------------------------------

@dataclass
class Script:
    """A list of turns. Each turn is a list of pieces:

        ("c", "answer text")      -> a content chunk
        ("r", "thinking text")    -> a reasoning chunk
        TC("read_file", "{...}")  -> a tool call chunk

    A turn with no tool calls ends the agent loop. When the script runs
    out, an empty answer is returned (so a runaway loop terminates).
    """

    turns: list = field(default_factory=list)
    prompt_tokens: int = 100
    completion_tokens: int = 20
    finish_reason: str = "stop"      # what the fake server reports at the end
    calls: list = field(default_factory=list)      # every request we received

    def __post_init__(self):
        self._i = 0

    def next_turn(self) -> list:
        if self._i < len(self.turns):
            turn = self.turns[self._i]
            self._i += 1
            return turn
        return []

    # --- introspection used by the suites -------------------------------
    @property
    def used(self) -> int:
        return self._i

    def last_request(self) -> dict:
        return self.calls[-1] if self.calls else {}

    def prompt_sizes(self) -> list:
        """Approximate prompt size (chars) of every request we received."""
        return [sum(len(str(m.get("content") or "")) for m in c.get("messages", []))
                for c in self.calls]

    def tool_names(self) -> list:
        """Every tool name the harness offered on the last request."""
        req = self.last_request()
        return [t.get("function", {}).get("name") for t in (req.get("tools") or [])]


class _Completions:
    def __init__(self, script: Script):
        self.script = script

    def create(self, **kwargs):
        self.script.calls.append(kwargs)
        turn = self.script.next_turn()
        chunks = []
        for piece in turn:
            if isinstance(piece, TC):
                d = Delta(tool_calls=[types.SimpleNamespace(
                    index=piece.index,
                    id=piece.id,
                    function=Fn(piece.name, piece.arguments))])
                chunks.append(Chunk(d))
            elif isinstance(piece, tuple):
                kind, value = piece
                if kind == "c":
                    chunks.append(Chunk(Delta(content=value)))
                elif kind == "r":
                    chunks.append(Chunk(Delta(reasoning=value)))
                elif kind == "u":
                    chunks.append(Chunk(Delta(), usage=Usage(*value)))
        # a finish_reason + usage on the last chunk, like a real server
        chunks.append(Chunk(Delta(), usage=Usage(self.script.prompt_tokens,
                                                 self.script.completion_tokens),
                            finish_reason=self.script.finish_reason))
        return chunks


def make_chat(script: Script):
    """Build a drop-in replacement for llm.chat() driven by the script.

    Same contract as llm.chat(): same arguments, same return object
    (content + tool_calls with .model_dump()), same on_token /
    on_thinking callbacks, same `stop` hook.
    """

    def fake_chat(messages, tools=None, model=None, on_token=None,
                  on_thinking=None, stop=None):
        parts: list[str] = []
        acc: dict = {}

        # record the request the way the real chat() would see it
        script.calls.append({
            "model": model,
            "messages": messages,
            "tools": tools,
            "max_tokens": 4096,
            "stream": True,
            "stream_options": {"include_usage": True},
        })

        for piece in script.next_turn():
            if stop is not None and stop():
                break
            if isinstance(piece, TC):
                slot = acc.setdefault(piece.index,
                                      {"id": "", "name": "", "arguments": ""})
                if piece.id:
                    slot["id"] = piece.id
                slot["name"] += piece.name
                slot["arguments"] += piece.arguments
            elif isinstance(piece, tuple):
                kind, value = piece
                if kind == "c":
                    parts.append(value)
                    if on_token:
                        on_token(value)
                elif kind == "r":
                    if on_thinking:
                        on_thinking(value)

        tool_calls = [types.SimpleNamespace(
            id=a["id"],
            type="function",
            function=Fn(a["name"], a["arguments"]),
            model_dump=lambda a=a: {"id": a["id"], "type": "function",
                                    "function": {"name": a["name"],
                                                 "arguments": a["arguments"]}})
            for a in acc.values()] or None
        return types.SimpleNamespace(content="".join(parts), tool_calls=tool_calls)

    return fake_chat


def install(script: Script) -> Script:
    """Point the harness at the script. Returns the script.

    `main.py:13` and `context.py:23` do `from llm import chat`, so patching
    `llm.chat` does NOT reach them — you must patch the *importing*
    module's binding. This patches main.chat and context.chat and leaves
    llm.chat alone (so llm.py's own streaming router stays testable;
    use install_client() for that).
    """
    import context
    import main

    fake = make_chat(script)
    main.chat = fake
    context.chat = fake
    return script


def install_client(script: Script) -> Script:
    """Patch llm.client so the REAL llm.chat() streams from the script.

    Used to benchmark llm.py itself (the <thinking> router, the tool-call
    accumulator) without a server.
    """
    client = types.SimpleNamespace(
        chat=types.SimpleNamespace(completions=_Completions(script)))
    llm.client = lambda model=None: client
    return script
