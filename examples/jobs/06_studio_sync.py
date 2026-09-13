"""Inspect the canonical graph that an authenticated ``plural run`` synchronizes."""

from __future__ import annotations

from _foundation import build_job

from plural.project import dumps

job = build_job()
payload = dumps(job)
print(payload)

assert "schema_version" not in payload
assert "revision:" not in payload
assert "kind: benchmark" in payload
print("Public payload ready; `plural run --hosted` explicitly publishes dependencies")
