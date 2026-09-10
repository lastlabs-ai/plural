---
route: /docs/concepts/hub
title: "Hub"
order: 180
description: "The hub is a listing of published Environment, Task, Verifier, AgentDefinition, Benchmark, and Harness revisions. It is not a marketplace: visibility and a readme, not payments or cross-account install."
audience: all
---
# Hub

The hub is a listing of published Environment, Task, Verifier,
AgentDefinition, Benchmark, and Harness revisions. It is not a marketplace:
visibility and a readme, not
payments or cross-account install.

Listings live in `hub_listings` (`object_type`, `slug`, `title`,
`readme_md`, `license`, `visibility`, `version`).

```bash
# Hosted API
# GET  /api/v1/hub/listings
# POST /api/v1/hub/listings
# GET  /api/v1/hub/listings/{slug}
```

Browse and publish from Plural Intel `/hub`.
