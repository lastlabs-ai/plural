---
route: /docs
title: Plural
order: 0
description: Intelligence should be plural. Evaluate the models that matter to you, route work to the right one, and train further when it is not good enough.
audience: all
nav: true
nav_group: Start
---
# Plural

We think [intelligence should be plural](https://lastlabs.ai/blog/intelligence-should-be-plural).
Not one brain with a billion prompts. Different people and companies have
different goals, values, and ways of seeing the world. That is a feature.

Alignment is not a problem one lab or a panel of third-party evaluators can
close for everyone. Two people can be misaligned with each other. That is
human nature. The future worth building is one that keeps diversity of thought
alive, not one that converges on a single way of thinking.

If an organization spent twenty years learning how it decides, some of that
should become learned behavior in *its* model. The model should get better at
being their model.

To do that, people and companies need to answer three questions:

1. **Which models are good at the work we care about?**
2. **Which model should we use for each task?**
3. **How do we train further when it is not good enough yet?**

Plural exists to make those three things straightforward: **evaluate**,
**route**, and **train**.

**Evaluate.** You define the world (an Environment), the piece of work (a
Task), and the score you believe (Verifiers). You run Agents built on catalog
models and keep the evidence: trajectory, artifacts, cost, latency, and the
exact version of every input behind each result.

**Route.** Once you trust the scores, you can send each task to the cheapest
intelligence that does it well. Sometimes that is a frontier model. Sometimes
it is a specialist. Sometimes it is a small model on a laptop. There is no
single best model — only the best one for a goal, a person, and a set of
constraints.

**Train.** When the best available model is still not yours, the same
Environments and Tasks become the setup for further training. Plural does not
replace your trainer. It gives you versioned work, honest scores, and exact
run records a trainer can consume.

In practice, a Plural project is a directory: one folder per Environment,
Task, Verifier, Harness, Agent, and Benchmark. The `plural` CLI and the
Python SDK load the same resources from it. Runs are local by default, and
each one is a Job whose inputs are pinned so you can rerun it exactly. When
you want hosted runs, you push the project to a private hosted project.

Start with [Core concepts](getting-started/concepts.md), then
[Getting started](getting-started.md). To see a finished project run offline
first, follow the [support queue tutorial](tutorials/support-queue.md). Coming
from 0.14? Read [Migrate to 0.15](migration/projects.md).
