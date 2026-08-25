"""Chat with an Anthropic model via your plural API key.

Requires ``PLURAL_API_KEY`` in your environment::

    export PLURAL_API_KEY=plural-...
    uv run python examples/routing/models/anthropic/basic.py
"""

from plural import Message, Plural

client = Plural()

response = client.chat(
    model="anthropic/claude-sonnet-4",
    messages=[Message(role="user", content="In one sentence, what is constitutional AI?")],
    temperature=0.2,
    max_tokens=128,
)

print(response.model)
print(response.text)
client.close()
