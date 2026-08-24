# API reference

## Client and request types

::: enroute.client.Enroute

::: enroute.types

## Tracing

::: enroute.tracing.schema.Trace

::: enroute.tracing.schema.TraceContext

::: enroute.tracing.schema.Decision

::: enroute.tracing.schema.Transition

::: enroute.tracing.resources.trace_json_schema

## Environments

`Environment.step()` is framework-owned and final. Tool environments use its
default dispatch behavior; scalar and custom text environments override
`apply_action()` and return `ActionResult`. `record_decision()` and
`finish_turn()` remain public for advanced manual integrations, but normal
`apply_action()` hooks should not call them.

::: enroute.environments.env.Environment

::: enroute.environments.action.ActionResult

::: enroute.environments.task.TaskData

::: enroute.environments.dataset.TaskDataset

::: enroute.environments.dataset.Dataset

::: enroute.environments.dataset.TraceFilter

::: enroute.environments.step.StepResult

::: enroute.environments.rollout.Rollout

::: enroute.environments.tool.tool

::: enroute.environments.types.Observation

::: enroute.environments.types.State

## Policies and runtime

::: enroute.environments.policy.Policy

::: enroute.environments.policy.EnroutePolicy

::: enroute.environments.policy.ScriptedPolicy

::: enroute.environments.runtime.Runtime

::: enroute.environments.runtime.LocalRuntime

::: enroute.environments.runtime.runtime_fingerprint

## Lifecycle and replay

::: enroute.environments.stop.EpisodeState

::: enroute.environments.stop.StopReason

::: enroute.environments.stop.EpisodeError

::: enroute.environments.replay.replay_actions

::: enroute.environments.replay.verify_replay

::: enroute.environments.replay.ReplayResult

::: enroute.environments.replay.ReplayMismatch

## Benchmarks

`Benchmark.from_policies(trace_writer=...)` records both successful and failed
episode traces when a writer is supplied. The caller owns and closes the
writer.

::: enroute.benchmarks.runner.Benchmark

::: enroute.benchmarks.runner.Report

::: enroute.benchmarks.runner.ModelStats

::: enroute.benchmarks.runner.CaseKey

::: enroute.benchmarks.runner.CaseResult

::: enroute.benchmarks.runner.WinRatePair

::: enroute.benchmarks.runner.RunManifest

::: enroute.benchmarks.runner.TaskDatasetMetadata

::: enroute.benchmarks.runner.TaskSetMetadata

## Routing

::: enroute.routing.policies
