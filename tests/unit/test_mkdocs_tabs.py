from __future__ import annotations

import importlib.util
from pathlib import Path

_PATH = Path(__file__).resolve().parents[2] / "scripts" / "mkdocs_tabs.py"
_SPEC = importlib.util.spec_from_file_location("mkdocs_tabs", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
mkdocs_tabs = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(mkdocs_tabs)


def test_tabs_become_pymdownx_tabs_with_indented_content() -> None:
    source = "\n".join(
        [
            "Intro.",
            "",
            ":::tabs",
            ":::tab API key",
            "Paste the key:",
            "",
            "```bash",
            "plural auth login --api-key-stdin",
            "```",
            ':::tab Browser "login"',
            "Opens a browser.",
            ":::",
            "",
            "After.",
        ]
    )
    assert mkdocs_tabs.convert_tabs(source) == "\n".join(
        [
            "Intro.",
            "",
            "",
            '=== "API key"',
            "",
            "    Paste the key:",
            "",
            "    ```bash",
            "    plural auth login --api-key-stdin",
            "    ```",
            "",
            '=== "Browser \\"login\\""',
            "",
            "    Opens a browser.",
            "",
            "",
            "After.",
        ]
    )


def test_markers_inside_code_fences_are_left_alone() -> None:
    source = "```text\n:::tabs\n:::tab A\n:::\n```\n::: plural.Client"
    assert mkdocs_tabs.convert_tabs(source) == source
