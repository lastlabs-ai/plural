---
route: /docs/project/harnesses
title: Harnesses
order: 65
description: Understand native loops and author a custom interaction strategy.
audience: all
nav: true
nav_group: Build
outcome: You can choose a Harness and understand its runtime, tool, and artifact contract.
---
# Harnesses

A Harness drives an Agent's interaction loop: model calls, messages, tool
dispatch, stopping, and output capture. Omit `Agent.harness` to use Plural's
native action or chat loop.

Treat the Harness as part of the experiment. “Model A with Harness X” and “Model A with Harness Y” are different agents even if their system instructions match.

## Use the built-in loop first

An Agent without an explicit Harness uses a native runner selected by the Job engine. With native Environment actions, it uses the action loop; without actions, it uses the chat loop. This keeps the smallest model-backed Agent configuration short.

Use a custom Harness when you need different tool behavior, transcript format, stopping logic, or an existing agent stack. See the [integration guide](../guides/harnesses.md) for supported workflows. An adapter still needs its executable and dependencies installed.

## Read the Harness contract

This file illustrates the fields used by a custom runner:

```yaml
kind: harness
name: my-loop
version: "0.1.0"
description: My custom Agent loop.
command: [python, harness.py]
source: .
capabilities: [shell]
models: ["openai/gpt-5.6-luna"]
auth: [environment]
secrets: [OPENAI_API_KEY]
environment: [OPENAI_BASE_URL]
outputs:
  - path: result.json
    required: true
    media_type: application/json
artifacts:
  - path: trajectory.jsonl
    required: true
    media_type: application/jsonl
trajectory: trajectory.jsonl
```

`command` is the executable argv. `models` declares supported model patterns.
`capabilities` declares tools the Harness may use. `secrets` declares
credential names an Agent may grant; every Agent grant must be a subset or
execution fails before forwarding. `environment` lists non-secret
configuration to forward when set. `source` is a directory path, archive URL,
or OCI URL. Remote sources require `digest`.

`outputs` and `artifacts` declare exact paths the runner must produce. If `trajectory` or `tito` is set, that path must also appear in `artifacts`. Use `healthcheck` for an optional pre-run command that checks installed dependencies.

Create the same object in Python with `Harness(...)`. Local source directories
are resolved and hashed at construction. Archive and OCI sources require an
explicit digest.

## Implement the runner

Plural sends a JSON request on stdin. The runner reads the Task and Agent from that request, calls the Environment commands, writes output files, and emits one terminal event on stdout.

For a successful custom run, a terminal event can look like:

```json
{
  "type": "result",
  "status": "succeeded",
  "outputs": ["result.json"],
  "artifacts": ["trajectory.jsonl"]
}
```

The listed files must exist and match the Harness declarations. Send ordinary
logs to stderr, keep structured events on stdout, honor the episode limits, and
record useful action/observation evidence. The
[support queue tutorial](../tutorials/support-queue.md) follows the built-in
runner.

## Environment tools and Harness tools

Native Environment actions are exposed under names such as `environment.categorize`. Harness-owned tools use names such as `harness.web_search`. The Environment may restrict the Harness's tools through `harness_policy`:

```yaml
harness_policy:
  denied_capabilities: [web_search]
```

This fragment denies a capability while leaving the default `allow_all` selection mode. Setting `mode: allowlist` means only the names in `allowed_harnesses` may run; an empty allowlist admits no explicit Harness. `allowed_capabilities` optionally sets a separate capability ceiling.

A supported tool denial is reported to the Agent so it can choose another
action. A disallowed Harness fails compatibility before execution. Network and
read-only-root policy can further restrict the effective grant. Native
Environment actions are not removed by a Harness capability denial.

Capability declarations and cooperative tool denials are not a substitute for operating-system enforcement of arbitrary code. Use a suitable [runtime](runtime.md) and trust boundary.

## Lock and distribute the implementation

A Harness lock includes its name, version, and content digest. Supported sources are local trees, archives, and OCI references. Remote sources require a digest and never bypass integrity checks.

Keep generated artifacts and caches out of the Harness source. If you move between machines, use a source the destination can materialize. An OCI Harness cannot currently be composed with a separate Environment image or build configuration in one Job.

## Capture training data

Train mode requires a Harness that sets `tito`, declares that path in
`artifacts`, and emits valid exact token records.

```python
harness = Harness(
    name="training-loop",
    command=("python", "harness.py"),
    source="harness",
    artifacts=("trajectory.jsonl", "tito.jsonl"),
    trajectory="trajectory.jsonl",
    tito="tito.jsonl",
)
```

A transcript or action list is not exact TITO. Do not set `tito` unless the
implementation records token IDs, aligned log probabilities, tokenizer, model,
and exact input/output/observation lengths.

[Training](../running/training.md) explains the fields and how to keep final evaluation scores separate from learning signals.
