# API reference

For a guided path, start with the [SDK and CLI coverage guide](feature-map.md).
The entries below document the actual public classes and methods.

## Client and request types

`Client.create(x)` and `Client.update(x)` sync an `Environment`, `Trace`,
`Benchmark` (after `run()`), or `Report` by slug. Agent templates are created
with `client.agents.templates.create(...)`.

::: plural.client.Client

::: plural.types

## Tracing

::: plural.tracing.schema.Trace

::: plural.tracing.schema.TraceContext

::: plural.tracing.schema.Turn

::: plural.tracing.schema.ActionStep

::: plural.tracing.schema.ReasoningBlock

::: plural.tracing.schema.Transition

::: plural.tracing.resources.trace_json_schema

## Environments

`Environment.step()` is framework-owned and final. Action environments use its
default dispatch behavior; scalar and custom text environments override
`apply_action()` and return `ActionResult`. `finish_turn()` remains public for
advanced manual integrations, but normal `apply_action()` hooks should not
call it.

::: plural.environments.env.Environment

::: plural.environments.action.ActionResult

::: plural.environments.task.TaskData

::: plural.environments.dataset.TaskDataset

::: plural.environments.dataset.Dataset

::: plural.environments.dataset.TraceFilter

::: plural.environments.step.StepResult

::: plural.environments.rollout.Rollout

::: plural.environments.action_registry.action

::: plural.environments.types.Observation

::: plural.environments.types.State

::: plural.environments.types.hidden

## Policies and runtime

::: plural.environments.policy.Policy

::: plural.environments.policy.PluralPolicy

::: plural.environments.policy.ScriptedPolicy

::: plural.environments.runtime.Runtime

::: plural.environments.runtime.LocalRuntime

::: plural.environments.runtime.runtime_fingerprint

## Lifecycle and replay

::: plural.environments.stop.EpisodeState

::: plural.environments.stop.StopReason

::: plural.environments.stop.EpisodeError

::: plural.environments.replay.replay_actions

::: plural.environments.replay.verify_replay

::: plural.environments.replay.ReplayResult

::: plural.environments.replay.ReplayMismatch

## Benchmarks

`Benchmark.from_policies(trace_writer=...)` records both successful and failed
episode traces when a writer is supplied. The caller owns and closes the
writer.

::: plural.benchmarks.runner.Benchmark

::: plural.benchmarks.runner.Report

::: plural.benchmarks.runner.ModelStats

::: plural.benchmarks.runner.CaseKey

::: plural.benchmarks.runner.CaseResult

::: plural.benchmarks.runner.WinRatePair

::: plural.benchmarks.runner.RunManifest

::: plural.benchmarks.runner.TaskDatasetMetadata

::: plural.benchmarks.runner.TaskSetMetadata

## Package and execution domain

The strict manifest fields are summarized in [Manifest fields](manifests.md);
the generated schemas are the serialization authority.

::: plural.domain

::: plural.execution.engine.Job

::: plural.execution.engine.Trial

::: plural.execution.engine.VerifierOutput

::: plural.execution.store.JobStore

## Harness packages and protocol

::: plural.harness.protocol

::: plural.harness.runner

::: plural.harness.packages

::: plural.harness.retrieval

## Sandbox providers

::: plural.sandbox.base.SandboxProvider

::: plural.sandbox.models

::: plural.sandbox.registry.ProviderRegistry

::: plural.sandbox.local.LocalProvider

::: plural.sandbox.docker.DockerProvider

::: plural.sandbox.daytona.DaytonaProvider

## CLI configuration and auth

::: plural.cli.config

::: plural.cli.auth

## Hosted Studio SDK

::: plural.studio.Studio

::: plural.studio.EnvironmentsAPI

::: plural.studio.AgentsAPI

::: plural.studio.BenchmarksAPI

::: plural.studio.TracesAPI

::: plural.studio.RemoteAgent

::: plural.studio.HarnessesAPI

::: plural.studio.JobsAPI

::: plural.studio.TrialsAPI

## Routing

::: plural.routing.policies

## Datasets and export

::: plural.environments.export.hf.to_huggingface_records

::: plural.environments.export.verifiers.to_verifiers_trace

## Catalog and costs

::: plural.catalog.models.ModelCatalog

::: plural.catalog.models.ModelSpec

::: plural.catalog.models.estimate_cost

::: plural.catalog.sync

## Trace storage and privacy

::: plural.tracing.writer.TraceWriter

::: plural.tracing.sinks

::: plural.tracing.redaction

## Provider interfaces and errors

::: plural.providers.base

::: plural.errors

## Local package loading

::: plural.cli.scaffold
