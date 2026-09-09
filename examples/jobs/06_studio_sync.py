"""Inspect legacy Studio payload offline; gate the live sync explicitly."""

from __future__ import annotations

import json
import os

from plural import Client, Environment
from plural.studio import environment_manifest

env = Environment(
    name="studio-payload-example",
    version="0.7.4",
    description="Legacy SDK Studio payload example.",
)
payload = {
    "name": env.name,
    "version": env.version,
    "instructions": env.system_prompt or "",
    "manifest": environment_manifest(env),
}
print(json.dumps(payload, indent=2, sort_keys=True))

if os.environ.get("PLURAL_RUN_STUDIO") == "1":
    with Client(project=os.environ["PLURAL_PROJECT"]) as client:
        created = client.create(env)
        print(f"created hosted Environment {created['environment_id']}")
else:
    print("Studio write gated; set PLURAL_RUN_STUDIO=1, PLURAL_API_KEY, and PLURAL_PROJECT")
