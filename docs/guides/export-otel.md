# Export to OpenTelemetry

```bash
pip install "plural[otel]"
```

```python
from plural import Client
from plural.tracing import MultiSink, JSONLSink, OTelSink

# Configure your TracerProvider elsewhere (ODLP, Datadog, Honeycomb, ...).
client = Client(
    providers={"openai": "..."},
    sink=MultiSink([JSONLSink(".plural/traces.jsonl"), OTelSink()]),
)
```

plural's `Trace` object remains canonical. `OTelSink` maps LLM steps onto Development-status `gen_ai.*` attributes. Prefer the plural schema for datasets and training; use OTel for live ops dashboards.
