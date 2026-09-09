# Build, evaluate, and use agents with Plural

Plural helps you define the work an AI system should do, test different models
and harnesses on that work, and keep a record of what happened. You can use the
Python SDK, the `plural` command-line interface, or both.

Start with an **environment**: the task instructions, data, operations, and
checks for your use case. Run a model against it, inspect the results, and
compare another model under the same conditions. Use **Plural Intel** to store
and retrieve hosted environments, agents, benchmarks, and results.

## Start here

1. [Install and authenticate](getting-started/setup.md). Set up Python, API
   keys, and your Plural Intel project.
2. [Choose your workflow](getting-started/concepts.md). Understand what you
   need to configure and which objects are local or hosted.
3. [Your first evaluation](quickstart.md). Run a small, scored example without
   an API key, then switch to a real model.
4. [Build a practical Python environment](tutorials/sdk-walkthrough.md).
   Add tools, tasks, scoring, model comparisons, and saved reports.
5. [Run packages from the CLI](tutorials/cli-walkthrough.md).
   Create an environment, harness, agent, benchmark, and job.
6. [Work with Plural Intel objects](guides/push-to-plural.md). Find, fetch,
   create, update, and reuse hosted objects.

**New to programming?** Read the setup and concepts pages first. The CLI
walkthrough explains each file and command. Running a prepared environment
needs configuration; implementing new tools and success checks needs code.

**Already have an application?** Start with [model calls and streaming](sdk/client.md),
then [traces and datasets](tutorials/traces-and-datasets.md).

## Go deeper when you need to

- [Stateful environments and custom actions](guides/write-environment.md)
- [Benchmark methodology and regression checks](guides/benchmark-models.md)
- [Run packages from Python](sdk/package-jobs.md)
- [Custom harnesses and adapters](guides/harnesses.md)
- [Docker, Daytona, retries, and regrading](guides/jobs.md)
- [Publish and sync package results](guides/studio-sync.md)
- [Permissions and isolation](operations/security.md)
- [Troubleshooting](operations/troubleshooting.md)

## Find every feature

The [SDK and CLI coverage guide](reference/feature-map.md) connects each feature
to its walkthrough and reference. The [Python API reference](reference/api.md)
and [generated CLI reference](reference/cli-commands.md) provide exact signatures
and options.

The package currently includes both a Python episode API and an alpha package
execution API. Both are documented; they are not interchangeable objects.
Hosted features require a compatible Plural Intel deployment. See
[current limitations](reference/limitations.md) before planning a deployment.
