"""Chat with a Fireworks model via your plural API key.

Requires ``PLURAL_API_KEY`` in your environment::

    export PLURAL_API_KEY=plural-...
    uv run python examples/routing/models/fireworks/basic.py
"""

from plural import Message, Plural

client = Plural()

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

print(response.model)
print(response.text)
client.close()
