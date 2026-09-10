"""Generate deterministic JSON Schemas for the package/CLI foundation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pydantic import BaseModel

from plural.cli.config import CLIConfig, ResolvedContext
from plural.cli.scaffold import JobFile
from plural.domain import (
    AgentTemplate,
    BenchmarkDefinition,
    EnvironmentManifest,
    HarnessManifest,
    HarnessPackage,
    JobSpec,
    TrialReceipt,
    TrialSpec,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "src" / "plural" / "schemas" / "packages"
MODELS: tuple[type[BaseModel], ...] = (
    EnvironmentManifest,
    HarnessManifest,
    HarnessPackage,
    AgentTemplate,
    BenchmarkDefinition,
    JobFile,
    JobSpec,
    TrialSpec,
    TrialReceipt,
    CLIConfig,
    ResolvedContext,
)


def rendered_schemas() -> dict[Path, str]:
    """Return every expected schema path and canonical contents."""
    return {
        OUTPUT / f"{model.__name__}.schema.json": (
            json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n"
        )
        for model in MODELS
    }


def main() -> int:
    """Write schemas, or report drift without modifying files.

    Returns:
        Zero when schemas are current or written, otherwise one.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = rendered_schemas()
    if args.check:
        drift = [
            path.relative_to(ROOT)
            for path, content in expected.items()
            if not path.exists() or path.read_text(encoding="utf-8") != content
        ]
        if drift:
            print("Package schema drift:")
            for path in drift:
                print(f"  {path}")
            return 1
        print(f"Package schemas are current ({len(expected)} files).")
        return 0
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for path, content in expected.items():
        path.write_text(content, encoding="utf-8")
    print(f"Wrote {len(expected)} package schemas to {OUTPUT.relative_to(ROOT)}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
