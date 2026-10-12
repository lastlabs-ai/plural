"""Drift and packaging checks for public documentation artifacts."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from jsonschema.validators import validator_for

ROOT = Path(__file__).resolve().parents[2]


def _check(script: str) -> None:
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script), "--check"],
        cwd=ROOT,
        check=True,
    )


def test_package_schemas_do_not_drift() -> None:
    _check("generate_package_schemas.py")


def test_cli_reference_does_not_drift() -> None:
    _check("generate_cli_reference.py")


def test_generated_field_docs_do_not_drift() -> None:
    _check("generate_docs_fields.py")


def test_generated_api_docs_do_not_drift() -> None:
    _check("generate_docs_api.py")


def test_packaged_schemas_are_valid_json_schemas() -> None:
    paths = sorted((ROOT / "src" / "plural" / "schemas" / "packages").glob("*.json"))
    assert {path.name for path in paths} == {
        "Agent.schema.json",
        "AgentVerifier.schema.json",
        "Benchmark.schema.json",
        "DeterministicVerifier.schema.json",
        "Environment.schema.json",
        "HumanVerifier.schema.json",
        "Harness.schema.json",
        "Job.schema.json",
        "Task.schema.json",
    }
    for path in paths:
        schema = json.loads(path.read_text(encoding="utf-8"))
        validator_for(schema).check_schema(schema)
