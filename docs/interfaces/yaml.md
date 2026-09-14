---
route: /docs/interfaces/yaml
title: YAML and serialization
order: 125
description: Serialize the Python evaluation graph losslessly with identical public field names, defaults, references, and hashes.
audience: all
nav: true
nav_group: Interfaces
---
# YAML and serialization

YAML is a lossless public serialization of Python SDK objects. It is not a
second configuration model.

## One object per file

```yaml
kind: agent
model: openai/gpt-5.6-luna
name: careful
version: 1.0.0
provider: null
instructions: Use the available actions.
fallback_models: []
temperature: null
max_tokens: null
harness: null
auth_mode: environment
secret_names: []
metadata: {}
```

Dumped YAML includes defaults. Human-authored YAML may omit optional defaults;
loading produces the same values.

References are relative to the containing file:

```yaml
kind: task
name: ticket-1
version: 1.0.0
instructions: Resolve the support ticket.
goals: []
info:
  ticket_id: ticket-1
metadata: {}
environment: ../environment/environment.yaml
verifiers:
  - ../verifiers/correct.yaml
resources: []
initial_state: {}
reset_options: {}
```

And a Job:

```yaml
kind: job
source: benchmark.yaml
agents:
  - agents/careful.yaml
mode: eval
attempts: 1
concurrency: 1
per_runtime_concurrency: 1
priority: 0
retry:
  max_retries: 0
  initial_backoff_seconds: 0.25
  max_backoff_seconds: 10.0
  multiplier: 2.0
  retryable_codes:
    - rate_limited
    - provider_unavailable
    - timeout
    - runtime_unavailable
```

## Python-backed Environments

YAML can reference an Environment subclass and its package adapter:

```yaml
kind: environment
python: world.py:SupportQueue
name: support-queue
version: 1.0.0
package:
  command: [python, commands.py]
  source: .
```

Generate this form with `plural.project.dump`, which records the source digest;
do not hand-copy a stale digest.

## Round-trip guarantee

```python
from plural.project import dump, load

dump(job, "job.yaml")
restored = load("job.yaml")
assert restored.content_hash == job.content_hash
assert restored.plan == job.plan
```

The resolver also supports inline nested objects and `{ref: path}` or
`{$ref: path}` mappings. Prefer simple path references in maintained projects
so each authored object can be reviewed and versioned independently.

Use only the object and field names shown in this guide and the generated field
catalog. Implementation and migration records are not part of the public
authoring graph.
