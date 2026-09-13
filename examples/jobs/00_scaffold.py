"""Scaffold and validate a Python-first public Job project."""

from __future__ import annotations

import tempfile
from pathlib import Path

from typer.testing import CliRunner

from plural.cli.main import app


def call(*args: str) -> str:
    """Invoke one CLI command and fail with its captured diagnostics."""
    result = CliRunner().invoke(app, list(args), color=False)
    if result.exit_code != 0:
        raise RuntimeError(result.output) from result.exception
    return result.output


with tempfile.TemporaryDirectory(prefix="plural-scaffold-") as temporary:
    root = Path(temporary)
    call("init", str(root))
    call("validate", str(root / "project.yaml"))
    call("inspect", str(root / "project.py") + ":job")
    print(f"scaffolded and validated {root / 'project.yaml'}")
