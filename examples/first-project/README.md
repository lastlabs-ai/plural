# First Plural project

This support-ticket example uses Plural's typed Environment API, native model
loop, deterministic evidence, two Agents, and a three-Task Benchmark.

From an environment with the current Plural checkout installed:

```bash
python build.py
plural run job.yaml --dry-run
```

To execute, configure `OPENAI_API_KEY`, then run one Job:

```bash
plural run job.yaml
```

Or compare both Agents with bounded concurrency:

```bash
plural run benchmark.yaml \
  --agent agents/careful.yaml \
  --agent agents/concise.yaml \
  --concurrency 2
```

These commands call a model and can incur charges. Local orchestration does not
mean no network. This starter intentionally uses the unsafe local Runtime for
easy inspection.

The complete explanation is in `docs/tutorials/support-queue.md`. `build.py`
rewrites generated YAML; edit the Python source for reproducible changes.
