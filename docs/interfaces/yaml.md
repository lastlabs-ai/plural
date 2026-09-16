---
route: /docs/interfaces/yaml
title: YAML and serialization
order: 125
description: Configure the same Tasks, Agents, and Jobs in YAML, with Python files supplying executable behavior.
audience: all
nav: true
nav_group: Interfaces
---
# YAML and serialization

Use Python to define behavior and YAML to organize reusable configuration. Both describe the same Plural objects and produce the same Job plan when their values match.

## Start with a small configuration

An Agent file can contain just the values you want to set:

```yaml
kind: agent
name: careful
model: openai/gpt-5.6-luna
instructions: Use the available actions and check the result before finishing.
```

To attach a built-in Harness, keep the name compact. Do not embed a generated Harness object:

```yaml
kind: agent
name: support-claude
model: anthropic/claude-sonnet-5
harness: claude-code
harness_kwargs:
  reasoning_effort: high
```

Custom Harness behavior stays in Python. Reference its class directly:

```yaml
kind: agent
name: support-custom
model: openai/gpt-5.6-luna
harness: harness.py:SupportHarness
```

Plural loads the subclass, hashes its directory, and calls its `run` method.
There is no command or source block to keep in sync.

Optional fields use the same defaults as the Python SDK. Exported YAML may include those defaults explicitly.

## Reference other files

Paths resolve relative to the file that contains the reference. For example, `tasks/ticket-1.yaml` can use:

```yaml
kind: task
name: ticket-1
version: 1.0.0
instructions: Inspect, categorize, answer, and resolve the ticket.
info:
  ticket_id: ticket-1
environment: ../environment/environment.yaml
verifiers:
  - ../verifiers/correct.yaml
```

A Job selects a Benchmark and the Agents to run:

```yaml
kind: job
source: benchmark.yaml
agents:
  - agents/careful.yaml
  - agents/concise.yaml
attempts: 2
concurrency: 2
```

The default mode is `eval`. With three Tasks and two Agents, this Job plans twelve Trials: two attempts for each Agent and Task pair.

## Include Python behavior

An Environment needs executable code as well as configuration. This file references a class beside it and supplies the required Runtime:

```yaml
kind: environment
python: world.py:SupportQueue
name: support-queue
version: 1.0.0
runtime:
  provider: local
  allow_unsafe_local: true
```

Plural loads the class and hashes its source directory. The [support queue tutorial](../tutorials/support-queue.md) provides the implementation and generates its YAML for you.

## Export and reload

Given a Python `job` object:

```python
from plural.project import dump, load

dump(job, "job.yaml")
restored = load("job.yaml")
assert restored.content_hash == job.content_hash
assert restored.plan == job.plan
```

Or export from the CLI:

```bash
plural export job.py:job --output job.yaml
plural validate job.yaml
plural run job.yaml --dry-run
```

Use `dump` or `plural export` to generate source references and hashes. Keep generated configuration outside source directories when writing it would change a packaged source hash.

Inline nested objects and reference mappings are also supported. Simple file paths usually make larger projects easier to review.
