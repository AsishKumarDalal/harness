"""llm.py — the only file that talks to the model."""

from openai import OpenAI

import config
from config import require_api_key

_clients: dict[tuple, OpenAI] = {}     # one client per (base url, api key)
_last_usage: dict = {}

_OPEN_TAGS = ("<thinking>", "<think>")
_CLOSE_TAGS = ("</thinking>", "</think>")


class _Fn:
    def __init__(self, name="", arguments=""):
        self.name = name
        self.arguments = arguments


class _TC:
    def __init__(self, tc_id, name, arguments):
        self.id = tc_id
        self.type = "function"
        self.function = _Fn(name, arguments)

    def model_dump(self):
        return {"id": self.id, "type": self.type,
                "function": {"name": self.function.name,
                             "arguments": self.function.arguments}}


class _Msg:
    def __init__(self, content, tool_calls):
        self.content = content
        self.tool_calls = tool_calls


def _find_tag(text, tags):
    """Return (index, tag) for the earliest tag in text, or (-1, None)."""
    best_i, best = -1, None
    for t in tags:
        i = text.find(t)
        if i >= 0 and (best_i == -1 or i < best_i):
            best_i, best = i, t
    return best_i, best


class _Router:
    """Splits streamed content into answer text and <thinking>…</thinking> text."""

    def __init__(self, on_answer, on_thinking):
        self.answer = on_answer or (lambda _: None)
        self.think = on_thinking or (lambda _: None)
        self.in_think = False
        self.carry = ""

    def _route(self, text):
        if text:
            (self.think if self.in_think else self.answer)(text)

    def feed(self, piece: str):
        text = self.carry + piece
        self.carry = ""
        while text:
            tags = _CLOSE_TAGS if self.in_think else _OPEN_TAGS
            i, tag = _find_tag(text, tags)
            if i < 0:
                keep = max(len(t) for t in tags) - 1   # tail might be a split tag
                if len(text) > keep:
                    self._route(text[:-keep])
                    self.carry = text[-keep:]
                else:
                    self.carry = text
                return
            self._route(text[:i])
            text = text[i + len(tag):]
            self.in_think = not self.in_think

    def finish(self):
        self._route(self.carry)
        self.carry = ""


def endpoint_for(model: str | None) -> tuple[str | None, str | None]:
    """The base url and api key to use for a model.

    A model added through /model has its own endpoint (saved in
    $HARNESS_HOME/settings.json); everything else uses the .env settings.
    """
    try:
        entry = config.provider_for_model(model or config.MODEL)
    except Exception:
        entry = None
    if entry:
        return (entry.get("base_url") or None), (entry.get("api_key") or None)
    return config.BASE_URL, (config.API_KEY or None)


def client(model: str | None = None) -> OpenAI:
    """The OpenAI client for a model (one client per endpoint)."""
    base_url, api_key = endpoint_for(model)
    key = (base_url, api_key)
    if key not in _clients:
        kwargs = {"api_key": api_key or require_api_key()}
        if base_url:
            kwargs["base_url"] = base_url
        _clients[key] = OpenAI(**kwargs)
    return _clients[key]


def list_models(base_url: str, api_key: str) -> list[str]:
    """The model names an endpoint offers (for the /model window)."""
    kwargs = {"api_key": api_key or require_api_key()}
    if base_url:
        kwargs["base_url"] = base_url
    probe = OpenAI(**kwargs)
    names = [getattr(m, "id", "") for m in probe.models.list()]
    return sorted(name for name in names if name)


def chat(messages: list, tools: list | None = None, model: str | None = None,
         on_token=None, on_thinking=None, stop=None) -> object:
    """Stream the reply. Answer tokens go to on_token, reasoning to on_thinking.

    stop: optional callable; when it returns True the stream is closed and the
    partial reply is returned (used by the TUI to interrupt a generation).
    """
    kwargs = {
        "model": model or config.MODEL,   # read at call time: /model changes it
        "messages": messages,
        "max_tokens": 4096,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if tools:
        kwargs["tools"] = tools

    stream = client(kwargs["model"]).chat.completions.create(**kwargs)

    parts: list[str] = []
    acc: dict = {}            # index -> {id, name, arguments}
    usage = None

    def answer(text):
        parts.append(text)
        if on_token:
            on_token(text)

    router = _Router(answer, on_thinking)

    for chunk in stream:
        if stop is not None and stop():
            try:
                stream.close()
            except Exception:
                pass
            break
        if getattr(chunk, "usage", None):
            usage = chunk.usage
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if delta is None:
            continue
        reasoning = (getattr(delta, "reasoning_content", None)
                     or getattr(delta, "reasoning", None))
        if reasoning and on_thinking:
            on_thinking(reasoning)
        if delta.content:
            router.feed(delta.content)
        if delta.tool_calls:
            for tc in delta.tool_calls:
                slot = acc.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
                if tc.id:
                    slot["id"] = tc.id
                if tc.function:
                    if tc.function.name:
                        slot["name"] += tc.function.name
                    if tc.function.arguments:
                        slot["arguments"] += tc.function.arguments

    router.finish()

    if usage:
        _last_usage.update(prompt_tokens=usage.prompt_tokens,
                          completion_tokens=usage.completion_tokens)

    tool_calls = [_TC(a["id"], a["name"], a["arguments"]) for a in acc.values()] or None
    return _Msg("".join(parts), tool_calls)