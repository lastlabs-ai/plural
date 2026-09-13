---
route: /docs/reference/trace-schema
title: Trace Schema
order: 939
description: This page moved to Definitions. Open that guide for the current walkthrough and examples.
audience: all
nav: false
---
# Trace Schema

Plural client traces use schema version 3. [Download the JSON Schema](../schemas/trace.v3.json) for validation, or inspect `plural.tracing.schema.Trace` in the [API reference](api.md).

A native Harness trajectory, a Trial result, and a schema-v3 client Trace are different records. Use [Traces and Trials](../running/traces.md) to choose the right one. Fields are only meaningful when your selected integration records them; do not treat missing usage or content as zero activity.
