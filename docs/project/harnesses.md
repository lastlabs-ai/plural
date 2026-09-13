---
route: /docs/project/harnesses
title: Harnesses
order: 65
description: Understand native loops and package a custom interaction strategy.
audience: all
nav: false
outcome: You can choose a Harness and understand its runtime, tool, and artifact contract.
---
# Harnesses

A Harness drives the Agent's interaction with the world. It wraps the model call with messages, tool execution, stopping rules, and evidence capture. It can be a small loop, a vendor agent adapter, or a specialized strategy you already use in production.

Treat the Harness as part of the experiment. “Model A with Harness X” and “Model A with Harness Y” are different agents even if their system instructions match.

## Use the built-in loop first

An Agent without an explicit Harness uses a native runner selected by the Job engine. With native Environment actions, it uses the action loop; without actions, it uses the chat loop. This keeps the smallest model-backed Agent definition short.

Use a custom Harness when you need a different interaction protocol, tool behavior, transcript format, or existing agent stack. The package also has adapters for supported vendor workflows and ACP; see the [integration guide](../guides/harnesses.md) for their setup. An adapter still needs its actual executable and dependencies installed.

## Scaffold a runnable package

```bash
plural harness init harness --name my-loop
plural harness validate harness
plural agent init agents/custom.yaml --name custom \
  --model gpt-4.1-mini --harness harness
```

The scaffold writes `harness.yaml` and `harness.py`. It starts from a native chat runner; adapt its profile or implementation to the actions and protocol your world needs. Generating the files alone does not teach a custom model or vendor stack how to interact with an arbitrary Environment.

Run these commands from the project root. The Agent scaffold embeds the resolved Harness package and binding in the Agent YAML. If you edit the Harness afterward, regenerate or update that binding and validate it; a stale source digest should fail preflight.

## Read the package contract

This **package fragment** illustrates the fields used by a custom runner:

```yaml
definition:
  schema_version: "2"
  name: my-loop
  revision: "0.1.0"
  implementation: runnable
  protocol: plural-harness-v1
  command: [python, harness.py]
  capabilities: [shell]
  supported_models: ["openai/*"]
  auth_modes: [environment]
  secret_names: [OPENAI_API_KEY]
  environment_names: [OPENAI_BASE_URL]
  outputs:
    - path: result.json
      required: true
      media_type: application/json
  artifacts:
    - path: trajectory.jsonl
      required: true
      media_type: application/jsonl
  trajectory_path: trajectory.jsonl
source:
  kind: local
  uri: .
  unsafe_local: true
```

`command` is the executable argv. `supported_models` declares supported model patterns. `capabilities` declares tools the harness may use. `secret_names` declares credential names an Agent may grant; `environment_names` lists non-secret configuration to forward when set.

`outputs` and `artifacts` declare exact paths the runner must produce. If `trajectory_path` is set, it must also appear in `artifacts`. Use `healthcheck` for an optional pre-run command that checks installed dependencies.

A `declared` Harness describes a contract without a runnable implementation. Package Jobs require a `runnable` Harness with a command. ACP packages must declare `protocol: acp` and `protocol_adapter: acp-client-v1`; changing the protocol name does not implement an ACP client.

## Implement the protocol

The native package protocol sends a JSON request on stdin. The built-in native action runner reads the Task and Agent from that request, calls the Environment commands, writes output files, and emits a terminal protocol event on stdout.

For a successful custom run, a terminal event can look like:

```json
{
  "protocol": "plural-harness-v1",
  "type": "result",
  "status": "succeeded",
  "outputs": ["result.json"],
  "artifacts": ["trajectory.jsonl"]
}
```

The listed files must really exist and match the package declaration. Send ordinary logs to stderr, preserve the protocol on stdout, honor the episode limits, and record useful action/observation evidence. The [project walkthrough](../tutorials/first-project.md) follows the native runner in the package.

## Environment tools and Harness tools

Native Environment actions are exposed under names such as `environment.categorize`. Harness-owned tools use names such as `harness.web_search`. The Environment may restrict the Harness's tools through `harness_policy`:

```yaml
harness_policy:
  denied_capabilities: [web_search]
```

This fragment denies a capability while leaving the default `allow_all` package-selection mode. Setting `mode: allowlist` means only exact bindings in `allowed_harnesses` may run; an empty allowlist admits no explicit Harness. `allowed_capabilities` optionally sets a separate capability ceiling.

A supported tool denial is reported to the Agent so it can choose another action. A disallowed Harness binding fails compatibility before execution. Network and read-only-root policy can further restrict the effective grant. Native Environment actions are not removed by a Harness capability denial.

Capability declarations and cooperative tool denials are not a substitute for operating-system enforcement of arbitrary code. Use a suitable [runtime](runtime.md) and trust boundary.

## Lock and distribute the implementation

A Harness binding includes its name, revision, and digest. The complete package also includes its source. Supported source kinds are local trees, archives, and OCI references. Remote sources require a digest; local unsafe opt-in is only for local sources and never bypasses remote integrity checks.

Keep generated artifacts and caches out of the package source. If you move between machines, use a source the destination can actually materialize. An OCI Harness cannot currently be composed with a separate Environment image or build configuration in a package Job; choose a supported packaging arrangement.

## Capture training data

Train mode requires a Harness that declares `supports_tito: true`, names a `tito_path`, declares that path as an artifact, and emits valid exact token records. A chat transcript or support triage move list is not that token record. Do not add the flag to an implementation that cannot provide the data.

[Training](../running/training.md) explains the fields and how to keep final evaluation scores separate from learning signals.
