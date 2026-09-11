---
route: /docs/reference/api
title: "API reference"
order: 240
description: "Public Python classes and methods for the Plural package. MkDocs renders this page with mkdocstrings."
audience: all
nav: false
---
# API reference

For a guided path, start with [Getting started](../getting-started.md) and the [definition fields](definitions.md).
The entries below document the public classes and methods.

## Client and request types

`Client.create(x)` and `Client.update(x)` support the hosted object types
implemented by the connected deployment. Canonical local execution uses
`EnvironmentDefinition`, `AgentDefinition`, Task/Verifier revisions,
and Task-or-Benchmark `JobSpec` values.

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

## Package and execution domain

The canonical domain contains EnvironmentDefinition, AgentDefinition,
first-class Task and Verifier revisions, cross-Environment
BenchmarkDefinition, discriminated Job sources, Trial/TrialExecution,
ProgressEvent, and exact TITORecord. The generated schemas are the
serialization authority.

::: plural.domain

::: plural.execution.engine.Job

::: plural.execution.engine.Trial

::: plural.execution.engine.VerifierOutput

::: plural.execution.store.JobStore

## Environment authoring

::: plural.environments.env.Environment

::: plural.environments.env.action

::: plural.environments.env.rewarder

::: plural.environments.types

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

::: plural.studio.TasksAPI

::: plural.studio.VerifiersAPI

::: plural.studio.AgentsAPI

::: plural.studio.BenchmarksAPI

::: plural.studio.TracesAPI

::: plural.studio.HarnessesAPI

::: plural.studio.JobsAPI

::: plural.studio.TrialsAPI

::: plural.studio.ReviewsAPI

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
