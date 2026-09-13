---
route: /docs/tutorials/cli-walkthrough
title: "Run your first Job"
order: 450
description: "Create, validate, inspect, export, and locally dry-run a public evaluation graph from the command line."
audience: all
nav: false
---
# Run your first Job

```bash
plural init demo
cd demo
plural validate project.py:job
plural inspect project.py:job
plural export project.py:job --output job.yaml
plural run job.yaml --dry-run
```

The CLI imports `project.py:job`, validates the public objects, and serializes
that same graph. A Task or Benchmark reference can add repeatable
`--agent path.py:agent` options.

Local execution is the default. Hosted submission is explicit:

```bash
plural run job.yaml --hosted
```
