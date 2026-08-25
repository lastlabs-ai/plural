"""Same quickstart, with an explicit local trace sink.

Requires ``PLURAL_API_KEY`` in your environment::

    export PLURAL_API_KEY=plural-...
    uv run python examples/routing/quickstart/with_tracing.py
"""

from pathlib import Path

from plural import Message, Plural
from plural.tracing import JSONLSink

Path(".plural/examples").mkdir(parents=True, exist_ok=True)

with Plural(
    sink=JSONLSink(".plural/examples/routing-quickstart.jsonl"),
    capture_content=True,
) as client:
    response = client.chat(
        model="openai/gpt-4o-mini",
        messages=[
            Message(role="user", content="Reply with one short sentence introducing yourself.")
        ],
        models=["anthropic/claude-sonnet-4"],
    )
    print(response.text)
    print("trace_id:", (response.raw or {}).get("plural_trace_id"))

print("traces → .plural/examples/routing-quickstart.jsonl")
