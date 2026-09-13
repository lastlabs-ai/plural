---
route: /docs/project/agents
title: "Agents"
order: 60
description: "Create catalog-backed Agents with instructions, provider validation, and an optional custom Harness."
audience: all
nav: true
nav_group: Project
outcome: You can create bundled and project-catalog Agents without global registration.
---
# Agents

An Agent owns a catalog model ID, instructions, optional provider preference,
and optional Harness. It does not own a Task or Environment.

```python
from plural import Agent

agent = Agent(
    model="openai/gpt-5.6-luna",
    instructions="Use the available actions and be concise.",
)
```

Bundled models and provider combinations are validated by default. Project
entries use an explicit context:

```python
from plural import CatalogContext, ModelCatalog, ModelSpec

context = CatalogContext(ModelCatalog(entries=[ModelSpec(id="project/model")]))
agent = context.agent(model="project/model")
```

The context is passed to project loaders and Job planning. It never mutates a
global registry, so ordinary `Agent(model="...")` continues to validate against
the bundled catalog.
