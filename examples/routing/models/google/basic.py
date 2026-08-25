"""Chat with a Google Gemini model via your plural API key.

Requires ``PLURAL_API_KEY`` in your environment::

    export PLURAL_API_KEY=plural-...
    uv run python examples/routing/models/google/basic.py
"""

from plural import Message, Plural

client = Plural()

response = client.chat(
    model="google/gemini-2.5-flash",
    messages=[Message(role="user", content="In one sentence, what is multimodal AI?")],
    temperature=0.2,
    max_tokens=128,
)

print(response.model)
print(response.text)
client.close()
