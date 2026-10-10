"""Command hooks shared by Apps that connect existing systems.

An MCP, OpenAPI, or data App can name a ``reset`` command that seeds the
system at the start of each episode and a ``snapshot`` command that prints
its state as JSON. Both run from the Environment workspace.
"""

from __future__ import annotations

import json
import shlex
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any


def argv(value: str | Sequence[str] | None) -> list[str]:
    """Split a command given as a string or a list.

    Returns:
        The argument list, empty for ``None``.
    """
    if value is None:
        return []
    return shlex.split(value) if isinstance(value, str) else [str(item) for item in value]


def run_hook(app: str, command: Sequence[str], *, stdin: str, cwd: Path, timeout: float) -> str:
    """Run one hook command and return what it printed.

    Returns:
        Its standard output.

    Raises:
        RuntimeError: When the command fails.
    """
    completed = subprocess.run(  # noqa: S603 - the App's declared hook
        list(command),
        input=stdin.encode(),
        capture_output=True,
        cwd=str(cwd),
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).decode(errors="replace")[-2000:]
        raise RuntimeError(
            f"App {app!r} hook {' '.join(command)} failed ({completed.returncode}): {detail}"
        )
    return completed.stdout.decode(errors="replace")


def snapshot_output(app: str, output: str) -> Any:
    """Parse a snapshot hook's output.

    Returns:
        The JSON value, or ``None`` when it printed nothing.

    Raises:
        ValueError: When the output is not JSON.
    """
    try:
        return json.loads(output) if output.strip() else None
    except json.JSONDecodeError as exc:
        raise ValueError(f"App {app!r} snapshot did not print JSON: {exc}") from exc


__all__ = ["argv", "run_hook", "snapshot_output"]
