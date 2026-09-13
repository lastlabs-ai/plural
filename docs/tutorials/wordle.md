---
route: /docs/tutorials/wordle
title: Wordle
order: 115
description: 'Build Wordle from the seven public SDK concepts, package its action adapter, and run the equivalent generated YAML.'
audience: all
nav: true
nav_group: Tutorial
outcome: You can follow Python, YAML, and CLI parity in a complete local example.
---
# Wordle

The canonical example is `examples/wordle`.

```bash
cd examples/wordle
plural validate job.py:job
plural run job.py:job --dry-run
plural validate job.yaml
plural run job.yaml --dry-run
```

The short files each own one concept:

- `wordle.py` defines typed state, observation, and the `guess` action.
- `environment.py` selects `Runtime` and calls `.package(...)`.
- `verifier.py` defines the completed-Trial Verifier.
- `task.py`, `benchmark.py`, `agent.py`, and `job.py` compose public objects.
- `job.yaml` is generated from that public Job.

`advanced.py` separately demonstrates a custom Harness, Agent and Human
Verifiers, and a Rewarder so the beginner graph stays small.

Python and YAML produce equal Job plans and hashes. No beginner file imports an
internal definition, binding, action manifest, runtime alias, or native profile.
