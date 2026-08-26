"""Chat with an OpenAI model via your plural API key.

Requires ``PLURAL_API_KEY`` in your environment::

    export PLURAL_API_KEY=plural-...
    uv run python examples/routing/models/openai/basic.py
"""

from plural import Client, Message

client = Client()

response = client.chat(
    model="openai/gpt-4o-mini",
    messages=[
        Message(role="user", content="In one sentence, what is a transformer neural network?")
    ],
    temperature=0.2,
    max_tokens=128,
)

print(response.model)
print(response.text)
client.close()
