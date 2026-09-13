---
route: /docs/project/tasks
title: Tasks
order: 40
description: Combine instructions, one Environment, Verifiers, resources, and initial state into one versioned unit of work.
audience: all
nav: true
nav_group: Project
outcome: You can author a Task identically in Python or YAML.
---
# Tasks

A Task supplies instructions and case information to one Environment, then
attaches the Verifiers that define success.

```python
from plural import Task

task = Task(
    name="ticket-1",
    instructions="Categorize the support ticket.",
    info={"ticket_id": "ticket-1"},
    environment=environment,
    verifiers=[correct],
)
```

Equivalent YAML uses those exact fields:

```yaml
kind: task
name: ticket-1
version: 0.1.0
instructions: Categorize the support ticket.
info:
  ticket_id: ticket-1
environment: environment.py:environment
verifiers:
  - verifier.py:correct
```

Task content identity includes the resolved Environment and Verifier hashes.
Initial state is checked against the Environment state schema before planning.
