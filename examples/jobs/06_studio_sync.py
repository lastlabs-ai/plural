"""Inspect the canonical graph that an authenticated ``plural run`` synchronizes."""

from __future__ import annotations

import json

from _foundation import build_job

spec = build_job()
payload = spec.model_dump(mode="json", exclude_none=True)
print(json.dumps(payload, indent=2, sort_keys=True))

assert payload["schema_version"] == "2"
assert payload["source"]["kind"] == "benchmark"
assert "runtime" not in payload
assert all("environment" not in binding["agent"] for binding in payload["agents"])
print("Canonical payload ready; `plural run` publishes dependencies before the hosted Job")
