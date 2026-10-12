# Schema-v2 Benchmark examples

Both examples are credential-free planning demonstrations:

```bash
uv run python examples/benchmarking/01_compare_models.py
uv run python examples/benchmarking/02_compare_policies.py
```

They build first-class Task and Verifier revisions, Environment-independent
AgentDefinitions, and Benchmark sources. The first Benchmark intentionally
spans two Environments. Attempts create Trials; runtime retries would create
TrialExecutions without changing the plan.

Use `Job(...).run()` with runnable Harnesses and implemented Verifier commands
for execution.
