"""Your own model, with local tracing.

export CUSTOM_BASE_URL=http://127.0.0.1:8000/v1
export CUSTOM_MODEL=meta-llama/Meta-Llama-3.1-8B-Instruct
uv run python examples/routing/custom/with_tracing.py
"""

import os
from pathlib import Path

from plural import Message, Plural
from plural.providers import OpenAICompatible
from plural.tracing import JSONLSink

base_url = os.environ.get("CUSTOM_BASE_URL", "http://127.0.0.1:8000/v1")
api_key = os.environ.get("CUSTOM_API_KEY", "EMPTY")
server_model = os.environ.get("CUSTOM_MODEL", "my-model")

Path(".plural/examples").mkdir(parents=True, exist_ok=True)

with Plural(
    providers={
        "custom": OpenAICompatible(
            api_key=api_key,
            base_url=base_url,
            name="custom",
        )
    },
    sink=JSONLSink(".plural/examples/routing-custom.jsonl"),
    capture_content=True,
) as client:
    response = client.chat(
        model=f"custom/{server_model}",
        messages=[Message(role="user", content="In one sentence, introduce yourself.")],
        temperature=0.2,
        max_tokens=128,
    )
    print(response.text)
    print("trace_id:", (response.raw or {}).get("plural_trace_id"))
