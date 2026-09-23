"""Scaffold a project in the standard layout and see what validation asks for."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from typer.testing import CliRunner

from plural.cli.main import app


def call(*args: str, ok: bool = True) -> str:
    """Invoke one CLI command; fail unless it exits the way ``ok`` expects."""
    result = CliRunner().invoke(app, list(args), color=False)
    if (result.exit_code == 0) != ok:
        raise RuntimeError(result.output) from result.exception
    return result.output


with tempfile.TemporaryDirectory(prefix="plural-scaffold-") as temporary:
    os.chdir(temporary)
    os.environ["PLURAL_CONFIG_HOME"] = str(Path(temporary) / "config")
    call("project", "init", "demo")
    os.chdir("demo")
    for kind, name in (("env", "queue"), ("verifier", "resolved"), ("task", "refund")):
        call(kind, "init", name)
    print(call("task", "list", "--local"))
    # Scaffolds are deliberately incomplete; validation says what to fill in.
    print(call("task", "validate", "refund", ok=False))
    print(f"scaffolded {Path.cwd() / 'project.yaml'}")
