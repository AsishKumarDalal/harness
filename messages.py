""" the agent's live memory, written through to the notebook."""

import sessions


class Conversation:
    def __init__(self, system_prompt: str, session_id: str | None = None):
        self.system_prompt = system_prompt
        self.session_id = session_id
        self.history: list[dict] = [{"role": "system", "content": system_prompt}]

    def add_user(self, content: str) -> dict:
        msg = {"role": "user", "content": content}
        self.history.append(msg)
        sessions.add_message(self.session_id, "user", content)
        return msg

    def add_assistant(self, reply) -> dict:
        msg = {"role": "assistant", "content": reply.content or ""}
        if reply.tool_calls:
            msg["tool_calls"] = [c.model_dump() for c in reply.tool_calls]
        self.history.append(msg)
        sessions.add_message(self.session_id, "assistant", msg["content"],
                             tool_calls=msg.get("tool_calls"))
        return msg

    def add_tool(self, tool_call_id: str, content: str) -> dict:
        msg = {"role": "tool", "tool_call_id": tool_call_id, "content": content}
        self.history.append(msg)
        sessions.add_message(self.session_id, "tool", content,
                             tool_call_id=tool_call_id,
                             tool_name=self._tool_name(tool_call_id))
        return msg

    def _tool_name(self, tool_call_id: str) -> str:
        """Which tool produced this result (for /search)?"""
        for m in reversed(self.history):
            for tc in m.get("tool_calls") or []:
                if tc.get("id") == tool_call_id:
                    return (tc.get("function") or {}).get("name", "")
        return ""

    def sync(self) -> None:
        """After compaction: make the notebook's active rows match this history."""
        sessions.sync(self.session_id, self.history)


def default_system_prompt() -> str:
    """The base instructions, plus the skills this project can load."""
    base = (
        "You are a coding agent. You have tools, use them as needed. "
        "Inspect before acting. If a tool errors, adjust and retry. Be concise."
    )
    try:
        import skills
        extra = skills.prompt_line()
    except Exception:
        extra = ""
    return f"{base}\n\n{extra}" if extra else base