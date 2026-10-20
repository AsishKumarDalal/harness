"""Test: can k2-horizon-mova-36b-a4b emit tool calls (and finish the loop)?
Run:  .venv/bin/python test/test_tool_call.py   (from project root)
Stage 1 decides support: does the model return tool_calls instead of guessing?
Stage 2 proves the full loop: harness runs the tool, feeds result, model answers.
"""
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

# --- endpoint from .env in project root (works from any run directory) ---
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
MODEL = os.getenv("MODEL")
BASE_URL = os.getenv("BASE_URL")
API_KEY = os.getenv("OPENAI_API_KEY", "ollama")

client = OpenAI(base_url=BASE_URL, api_key=API_KEY, timeout=600)

# --- one tiny tool, same style as the harness ---
def list_files() -> str:
    return "\n".join(sorted(os.listdir(".")))

SCHEMA = [{
    "type": "function",
    "function": {
        "name": "list_files",
        "description": "List files/folders in the current directory.",
        "parameters": {"type": "object", "properties": {}},
    },
}]

messages = [{
    "role": "user",
    "content": "How many Python files are in the current folder? "
               "You MUST call the list_files tool to find out, then "
               "answer with just the number and their names.",
}]

for turn in range(1, 4):
    r = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        tools=SCHEMA,
        max_tokens=4096,  # reasoning model: leave room
    )
    msg = r.choices[0].message

    if msg.tool_calls:
        print(f"stage {turn}: tool_calls captured  YES ->", end=" ")
        print(", ".join(c.function.name for c in msg.tool_calls))

        # assistant turn with its tool requests -> then tool results
        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [c.model_dump() for c in msg.tool_calls],
        })
        for c in msg.tool_calls:
            args = json.loads(c.function.arguments or "{}")
            print(f"          harness runs {c.function.name} {args}")
            messages.append({
                "role": "tool",
                "tool_call_id": c.id,
                "content": list_files()[:2000],
            })
        continue  # loop: model now sees the results

    print(f"stage {turn}: final answer came back")
    print("answer:", (msg.content or "").strip()[:500])
    if turn == 1:
        print("VERDICT: model IGNORED the tool request (tried to guess)")
    else:
        print("VERDICT: tool calling WORKS end-to-end ✅")
    break
else:
    print("VERDICT: never produced plain-text answer after 3 turns")
