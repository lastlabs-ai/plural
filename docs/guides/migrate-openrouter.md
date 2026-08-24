# Migrate from OpenRouter

## Constructor diff

```python
# Before (OpenAI SDK → OpenRouter)
from openai import OpenAI
client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key="...")

# After — primary: set ENROUTE_API_KEY, then
from enroute import Enroute
client = Enroute()

# After — secondary: bring-your-own upstream keys
client = Enroute(providers={"openai": "...", "anthropic": "..."})
```

## What maps cleanly

| OpenRouter | enroute |
| --- | --- |
| `model` | `model` (`author/slug`) |
| `models` fallback list | `models=` |
| `provider` preferences | `provider=ProviderPreferences(...)` |
| chat completions body | `ChatRequest` / `client.chat(...)` |

## What enroute adds

- Local/OTel **traces** with attempts
- **Environments** and **benchmarks**
- Offline **model catalog** + cost estimation

## Current package scope

The package documented here does not include hosted multi-provider billing,
a CLI, or a learned routing service.
