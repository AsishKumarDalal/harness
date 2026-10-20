"""Show what the model RETURNS when it wants to call a tool.
Run: .venv/bin/python test/see_tool_calls.py
"""
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
client = OpenAI(
    base_url=os.getenv("BASE_URL"),
    api_key=os.getenv("OPENAI_API_KEY", "ollama"),
    timeout=600,
)

TOOL = [{
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "Read a file's contents.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "file path"}},
            "required": ["path"],
        },
    },
}]

r = client.chat.completions.create(
    model=os.getenv("MODEL"),
    messages=[{"role": "user", "content": "write a 10 word simple story"}],
    tools=TOOL,
    max_tokens=4096,
)

msg = r

print(msg)