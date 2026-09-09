"""Generate the CLI command reference from the installed Typer command tree."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from typer.main import get_command
from typer.testing import CliRunner

from plural.cli.main import app

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "reference" / "cli-commands.md"
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _walk(command: object, path: tuple[str, ...] = ()) -> list[tuple[str, str]]:
    result = CliRunner().invoke(
        app,
        [*path, "--help"],
        color=False,
        env={"NO_COLOR": "1", "COLUMNS": "100"},
    )
    if result.exit_code != 0:
        raise RuntimeError(
            f"could not render help for {' '.join(('plural', *path))}: {result.output}"
        )
    rows = [(" ".join(("plural", *path)), ANSI.sub("", result.output).rstrip())]
    commands = getattr(command, "commands", None)
    if isinstance(commands, dict):
        for name in sorted(commands):
            rows.extend(_walk(commands[name], (*path, name)))
    return rows


def render() -> str:
    """Render deterministic Markdown from every actual command help page.

    Returns:
        Complete generated Markdown.
    """
    sections = [
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
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != content:
            print(f"CLI reference drift: {OUTPUT.relative_to(ROOT)}")
            return 1
        print("CLI reference is current.")
        return 0
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(content, encoding="utf-8")
    print(f"Wrote {OUTPUT.relative_to(ROOT)}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
