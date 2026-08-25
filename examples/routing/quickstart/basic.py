"""Quickstart: one plural API key, one chat call.

Requires ``PLURAL_API_KEY`` in your environment::

    export PLURAL_API_KEY=plural-...
    uv run python examples/routing/quickstart/basic.py
"""

from plural import Message, Plural

client = Plural()

response = client.chat(
    model="openai/gpt-4o-mini",
    messages=[Message(role="user", content="Reply with one short sentence introducing yourself.")],
    models=["anthropic/claude-sonnet-4"],  # optional fallbacks
)

print(response.text)
client.close()
