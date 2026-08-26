"""OpenAI model via plural, with local tracing.

Requires ``PLURAL_API_KEY`` in your environment::

    export PLURAL_API_KEY=plural-...
    uv run python examples/routing/models/openai/with_tracing.py
"""

from pathlib import Path

from plural import Client, Message
from plural.tracing import JSONLSink

Path(".plural/examples").mkdir(parents=True, exist_ok=True)

with Client(
    sink=JSONLSink(".plural/examples/routing-openai.jsonl"),
    capture_content=True,
) as client:
    response = client.chat(
        model="openai/gpt-4o-mini",
        messages=[
            Message(role="user", content="In one sentence, what is a transformer neural network?")
        ],
        temperature=0.2,
        max_tokens=128,
    )
    print(response.text)
    print("trace_id:", (response.raw or {}).get("plural_trace_id"))
