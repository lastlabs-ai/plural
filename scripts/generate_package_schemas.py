"""Generate deterministic JSON Schemas from public SDK models."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from plural import Agent, Benchmark, Harness, Task
from plural.environments.definition import EnvironmentDefinition
from plural.project import public_schema
from plural.verifiers import AgentVerifier, DeterministicVerifier, HumanVerifier

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "src" / "plural" / "schemas" / "packages"
MODELS: tuple[tuple[str, type[BaseModel]], ...] = (
    ("Environment", EnvironmentDefinition),
    ("Harness", Harness),
    ("Task", Task),
    ("DeterministicVerifier", DeterministicVerifier),
    ("AgentVerifier", AgentVerifier),
    ("HumanVerifier", HumanVerifier),
    ("Agent", Agent),
    ("Benchmark", Benchmark),
)


def _job_schema() -> dict[str, Any]:
    return {
        "title": "Job",
        "type": "object",
        "required": ["source", "agents"],
        "properties": {
            "source": {},
            "agents": {"type": "array", "minItems": 1},
            "mode": {"enum": ["eval", "train"], "default": "eval"},
            "attempts": {"type": "integer", "minimum": 1, "default": 1},
            "concurrency": {"type": "integer", "minimum": 1, "default": 1},
            "per_runtime_concurrency": {"type": "integer", "minimum": 1, "default": 1},
            "priority": {"type": "integer", "default": 0},
        },
    }


def rendered_schemas() -> dict[Path, str]:
    """Return every expected public schema and canonical contents."""
    rendered: dict[Path, str] = {}
    for name, model in MODELS:
        schema = public_schema(model)
        schema["title"] = name
        rendered[OUTPUT / f"{name}.schema.json"] = (
            json.dumps(schema, indent=2, sort_keys=True) + "\n"
        )
    rendered[OUTPUT / "Job.schema.json"] = (
        json.dumps(_job_schema(), indent=2, sort_keys=True) + "\n"
    )
    return rendered


def main() -> int:
    """Write schemas, or report drift without modifying files.

    Returns:
        Zero when current or written, otherwise one.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = rendered_schemas()
    extras = set(OUTPUT.glob("*.schema.json")) - set(expected) if OUTPUT.exists() else set()
    if args.check:
        drift = [
            path.relative_to(ROOT)
            for path, content in expected.items()
            if not path.exists() or path.read_text(encoding="utf-8") != content
        ]
        drift.extend(path.relative_to(ROOT) for path in sorted(extras))
        if drift:
            print("Package schema drift:")
            for path in drift:
                print(f"  {path}")
            return 1
        print(f"Package schemas are current ({len(expected)} files).")
        return 0
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for path in extras:
        path.unlink()
    for path, content in expected.items():
        path.write_text(content, encoding="utf-8")
    print(f"Wrote {len(expected)} package schemas to {OUTPUT.relative_to(ROOT)}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
