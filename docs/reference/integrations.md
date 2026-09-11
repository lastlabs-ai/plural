---
route: /docs/reference/integrations
title: "Integrations"
order: 230
description: "Providers, CI, OpenTelemetry, Studio sync, and bringing your own model gateway."
audience: all
nav: true
nav_group: Reference
---
# Integrations

The story pages stay on the graph. This page is the leftover wiring.

## Model providers

`Client` routes chat and completions through the configured gateway. Set `PLURAL_API_KEY` for Plural Intel, or point `OPENAI_BASE_URL` at OpenAI, Azure, Bedrock, Fireworks, or a local server. Optional extras: `plural[daytona]`, `plural[otel]`, `plural[keyring]`.

```bash
export PLURAL_API_KEY=...
plural auth login
```

A project-scoped key only sees that project. Account keys see what the account can see.

## CI

Run the same Job you run locally:

```bash
plural run job.yaml --offline
```

In a pipeline that should publish, set `PLURAL_API_KEY` and drop `--offline`. Treat the Job YAML as the contract: if `plural task validate` fails, the pin is wrong.

## OpenTelemetry

Install `plural[otel]` and export traces to your collector when you already have an OTEL pipeline. Plural Traces stay the episode record. OTEL is a sink, not a replacement.

## Studio sync

`plural run job.yaml` without `--offline` publishes Harnesses, Environments, Verifiers, Tasks, an optional Benchmark, then Agents, and submits the Job. Local `source.uri` paths must be visible to the worker. Offline Jobs are the path when the runtime lives only on your machine.

## Also

- [CLI commands](cli-commands.md) — every flag.
- [Definitions](definitions.md) — field lists.
- [Limitations](limitations.md) — known gaps.
- [Troubleshooting](../operations/troubleshooting.md) — failures and retries.
