"""Generate the canonical trace JSON Schema from the Pydantic model."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from plural.tracing import Trace

SCHEMA_ID = "https://pluralintel.com/schemas/trace.v2.json"
SCHEMA_TITLE = "Plural Trace"
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATHS = (
    REPOSITORY_ROOT / "src/plural/schemas/trace.v2.json",
    REPOSITORY_ROOT / "schemas/trace.v2.json",
    REPOSITORY_ROOT / "docs/schemas/trace.v2.json",
)


def generate_schema() -> dict[str, Any]:
    """Build the canonical serialization schema.

    Returns:
        The generated JSON Schema.
    """
    schema = Trace.model_json_schema(mode="serialization")
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = SCHEMA_ID
    schema["title"] = SCHEMA_TITLE
    return schema


def serialized_schema() -> str:
    """Return deterministic, human-readable schema JSON."""
    return json.dumps(generate_schema(), indent=2, sort_keys=True) + "\n"


def check_outputs(expected: str) -> int:
    """Return nonzero and report every missing or stale output."""
    stale = [
        path
        for path in OUTPUT_PATHS
        if not path.is_file() or path.read_text(encoding="utf-8") != expected
    ]
    if not stale:
        return 0

    print("Trace schema artifacts are stale. Regenerate with:", file=sys.stderr)
    print("  uv run python scripts/generate_trace_schema.py", file=sys.stderr)
    print("Stale paths:", file=sys.stderr)
    for path in stale:
        print(f"  {path.relative_to(REPOSITORY_ROOT)}", file=sys.stderr)
    return 1


def write_outputs(content: str) -> None:
    """Write all canonical and mirrored schema artifacts."""
    for path in OUTPUT_PATHS:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def main() -> int:
    """Generate artifacts or check that committed copies are current.

    Returns:
        Zero on success, or one if ``--check`` finds stale artifacts.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="report stale artifacts without rewriting them",
    )
    args = parser.parse_args()
    content = serialized_schema()
    if args.check:
        return check_outputs(content)
    write_outputs(content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
