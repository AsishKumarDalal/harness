
"""Sanity test: stream reasoning and answer from the remote model.
Run: python3 test/test_model.py
"""

import time
from openai import OpenAI

BASE_URL = "https://usgs-and-members-lesson.trycloudflare.com/v1"
API_KEY = "ollama"
MODEL = "k2-horizon-mova-36b-a4b"

client = OpenAI(
    base_url=BASE_URL,
    api_key=API_KEY,
    timeout=600,
)

print(f"Testing {MODEL} ...")
start = time.time()

r = client.chat.completions.create(
    model=MODEL,
    messages=[{"role": "user", "content": "write a love story of a creature"}],
    stream=True,
    reasoning_effort="none",
    stream_options={"include_usage": True},
)

reasoning_chunks = 0
answer_chunks = 0
usage = None
finish_reason = None

print("\n===== THINKING / REASONING =====\n", flush=True)

for chunk in r:
    if chunk.usage is not None:
        usage = chunk.usage

    if not chunk.choices:
        continue

    choice = chunk.choices[0]
    delta = choice.delta

    # Reasoning field names vary between compatible servers
    reasoning = (
        getattr(delta, "reasoning", None)
        or getattr(delta, "reasoning_content", None)
    )

    if reasoning:
        print(reasoning, end="", flush=True)
        reasoning_chunks += 1

    if choice.finish_reason:
        finish_reason = choice.finish_reason

    content = delta.content
    if content:
        if answer_chunks == 0:
            print("\n\n===== FINAL ANSWER =====\n", flush=True)
        print(content, end="", flush=True)
        answer_chunks += 1

secs = time.time() - start

print("\n\n===== STATS =====")
print(f"Time: {secs:.1f}s")
print(f"Reasoning chunks: {reasoning_chunks}")
print(f"Answer chunks: {answer_chunks}")
print(f"Finish reason: {finish_reason}")

if usage:
    print(f"Prompt tokens: {usage.prompt_tokens}")
    print(f"Completion tokens: {usage.completion_tokens}")
    print(f"Total tokens: {usage.total_tokens}")
