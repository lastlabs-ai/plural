"""Fireworks model via plural, with local tracing.

Requires ``PLURAL_API_KEY`` in your environment::

    export PLURAL_API_KEY=plural-...
    uv run python examples/routing/models/fireworks/with_tracing.py
"""

from pathlib import Path

from plural import Client, Message
from plural.tracing import JSONLSink

Path(".plural/examples").mkdir(parents=True, exist_ok=True)

with Client(
    sink=JSONLSink(".plural/examples/routing-fireworks.jsonl"),
    capture_content=True,
) as client:
    response = client.chat(
        model="fireworks/accounts/fireworks/models/llama-v3p3-70b-instruct",
        messages=[
            Message(
                role="user",
                content="In one sentence, why do teams use inference specialists like Fireworks?",
            )
        ],
        temperature=0.2,
        max_tokens=128,
    )
    print(response.text)
    print("trace_id:", (response.raw or {}).get("plural_trace_id"))
