---
route: /docs/concepts/dataset
title: "Datasets and revisioned Tasks"
order: 210
description: "Execution inputs are first-class TaskDefinition revisions, not rows owned by an Environment. Each Task pins one Environment revision and one or more weighted Verifier revisions."
audience: all
---
# Datasets and revisioned Tasks

Execution inputs are first-class `TaskDefinition` revisions, not rows owned by
an Environment. Each Task pins one Environment revision and one or more
weighted Verifier revisions.

Use `BenchmarkDefinition` to select ordered Tasks across one or more
Environments. The complete Task digests make the selection reproducible.

Trace datasets remain useful as output collections for analysis and export.
They are not substituted for Task revisions during schema-v2 planning.

## Privacy boundary

Task `instructions`, `info`, and metadata are visible to the Agent. Hidden
world state belongs to the Environment. Evaluator logic and connectivity belong
to each Verifier. Progress events omit hidden state and secrets.

Train-only exact TITO data is stored as immutable hashed artifacts. It is not
embedded in Task, Trace, or event JSON.

See [Benchmark](benchmark.md), [Environment](environment.md), and
[execution](execution.md).
