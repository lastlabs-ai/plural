# API reference

## Client and request types

::: plural.client.Client

::: plural.types

## Tracing

::: plural.tracing.schema.Trace

::: plural.tracing.schema.TraceContext

::: plural.tracing.schema.Decision

::: plural.tracing.schema.Transition

::: plural.tracing.resources.trace_json_schema

## Environments

`Environment.step()` is framework-owned and final. Tool environments use its
default dispatch behavior; scalar and custom text environments override
`apply_action()` and return `ActionResult`. `record_decision()` and
`finish_turn()` remain public for advanced manual integrations, but normal
`apply_action()` hooks should not call them.

::: plural.environments.env.Environment

::: plural.environments.action.ActionResult

::: plural.environments.task.TaskData

::: plural.environments.dataset.TaskDataset

::: plural.environments.dataset.Dataset

::: plural.environments.dataset.TraceFilter

::: plural.environments.step.StepResult

::: plural.environments.rollout.Rollout

::: plural.environments.tool.tool

::: plural.environments.types.Observation

::: plural.environments.types.State

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

## Routing

::: plural.routing.policies
