"""Generate the CLI command reference from the installed Typer command tree."""

from __future__ import annotations

import argparse
import difflib
import os
import re
from pathlib import Path

# Typer reads these at import time. Pin them before importing the CLI so Linux
# CI (GITHUB_ACTIONS + no TTY) and a local macOS terminal emit the same boxes.
os.environ["TERMINAL_WIDTH"] = "100"
os.environ["COLUMNS"] = "100"
os.environ["NO_COLOR"] = "1"
os.environ["_TYPER_FORCE_DISABLE_TERMINAL"] = "1"

from typer.main import get_command
from typer.testing import CliRunner

from plural.cli.main import app

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "reference" / "cli-commands.md"
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _normalize_help(text: str) -> str:
    cleaned = ANSI.sub("", text)
    return "\n".join(line.rstrip() for line in cleaned.splitlines()).rstrip()


def _walk(command: object, path: tuple[str, ...] = ()) -> list[tuple[str, str]]:
    result = CliRunner().invoke(
        app,
        [*path, "--help"],
        color=False,
        env={**os.environ, "NO_COLOR": "1", "COLUMNS": "100", "TERMINAL_WIDTH": "100"},
    )
    if result.exit_code != 0:
        raise RuntimeError(
            f"could not render help for {' '.join(('plural', *path))}: {result.output}"
        )
    rows = [(" ".join(("plural", *path)), _normalize_help(result.output))]
    commands = getattr(command, "commands", None)
    if isinstance(commands, dict):
        for name in sorted(commands):
            if getattr(commands[name], "hidden", False):
                continue
            rows.extend(_walk(commands[name], (*path, name)))
    return rows


def render() -> str:
    """Render deterministic Markdown from every actual command help page.

    Returns:
        Complete generated Markdown.
    """
    sections = [
        "---",
        "route: /docs/reference/cli-commands",
        'title: "Generated CLI command reference"',
        "order: 210",
        (
            'description: "Generated reference for every Plural CLI command '
            'and option exposed by the Typer application."'
        ),
        "audience: all",
        "nav: true",
        "nav_group: Reference",
        "---",
        "",
        "# Generated CLI command reference",
        "",
        "This file is generated from the Typer application. Do not edit it by hand.",
        "Run `uv run python scripts/generate_cli_reference.py` after changing the CLI.",
        "",
    ]
    for name, help_text in _walk(get_command(app)):
        sections.extend((f"## `{name}`", "", "```text", help_text, "```", ""))
    return "\n".join(sections)


def main() -> int:
    """Write the reference, or report drift.

    Returns:
        Zero when generated output is current or written, otherwise one.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    content = render()
    if args.check:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        if current != content:
            print(f"CLI reference drift: {OUTPUT.relative_to(ROOT)}")
            diff = difflib.unified_diff(
                current.splitlines(),
                content.splitlines(),
                fromfile=str(OUTPUT.relative_to(ROOT)),
                tofile="generated",
                lineterm="",
            )
            print("\n".join(diff))
            return 1
        print("CLI reference is current.")
        return 0
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(content, encoding="utf-8")
    print(f"Wrote {OUTPUT.relative_to(ROOT)}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
