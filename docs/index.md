---
route: /docs
title: Plural
order: 0
description: Build reproducible agent evaluations, compare models on your work, and keep the evidence behind every score.
audience: all
nav: true
nav_group: Start
outcome: You understand the shortest path from a real task to auditable model evidence.
---
# Plural

Plural evaluates agents on work you define. It runs catalog-backed models in
versioned Environments, scores completed Trials with your Verifiers, and keeps
the trajectory, artifacts, logs, evidence, and exact object pins behind each
result.

The primary workflow is evaluation:

1. Build an **Environment**, **Task**, and one or more **Verifiers**.
2. Pin Tasks in a versioned **Benchmark**.
3. Run catalog-backed **Agents** in a **Job**.
4. Inspect Trial evidence and compare quality, cost, and latency.

Those records can inform routing after the evaluation is trustworthy. Train
mode can also capture exact TITO records and Rewarder signals for a downstream
trainer. Plural does not implement optimization algorithms or update
model weights.

## Start here

Follow [Getting started](getting-started.md), then build the realistic
[support queue tutorial](tutorials/support-queue.md). Use the Build and Run
sections for each object and the generated references only when you need every
field.
