# Agent templates and instances

An **agent template** is immutable configuration: model + environment,
optionally plus a stamped harness. It is content-addressed.

An **agent instance** is a live hosted object created from a template. It
accumulates memory, skills, data, and experience counters as it runs.

## SDK

```python
client.agents.templates.list()
client.agents.templates.create(name="triage", model="openai/gpt-4.1-mini", ...)
client.agents.templates.revisions(template_id)

instance = client.agents.instances.create(template_id, name="triage-prod")
client.agents.instances.memories(instance["id"]).append("note", {"text": "..."})
client.agents.instances.skills(instance["id"]).upsert(
    "refunds",
    instructions="Prefer lookup_order before answering.",
    action_names=["lookup_order"],
)
client.agents.instances.data(instance["id"]).put("playbook", {"steps": []})
client.agents.instances.experience(instance["id"])
```

Harness events of type `memory`, `skill`, and `artifact` are accepted and
routed to the instance when a runnable harness exists. In this release they
are exercised by tests against the native runner.

## CLI

```bash
plural agent template init --name triage --model openai/gpt-4.1-mini --environment ./env
plural agent template show
plural agent template validate
plural agent instance list
plural agent instance show <id>
plural agent instance memory <id>
plural agent instance skills <id>
plural agent instance data <id>
plural agent instance experience <id>
```
