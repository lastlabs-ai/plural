---
route: /docs/cli
title: "Command-line interface"
order: 110
description: "Load, validate, inspect, export, and run the same public SDK objects from concise canonical commands."
audience: all
nav: false
---
# Command-line interface

The CLI is a thin boundary over `plural.project.Resolver` and public model
methods.

```bash
plural init
plural validate REF
plural inspect REF
plural export REF --output project.yaml
plural run REF --agent AGENT_REF --dry-run
plural models list
plural models show MODEL_ID
plural benchmarks show REF
plural benchmarks diff BEFORE AFTER
plural benchmarks export REF --output graph.yaml
plural auth status
```

`REF` may be YAML or `path.py:object`. A Job reference already contains Agents;
a Task or Benchmark run accepts one or more `--agent REF`.

Runs are local by default. `plural run REF --hosted` is the explicit hosted
path. CLI options only override fields when supplied; model constructors remain
the source of defaults and validation.

Use `--catalog plural.yaml` to add project model entries for loading, model
commands, and planning.
