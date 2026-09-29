"""MkDocs hook: render the docs' ``:::tabs`` blocks as pymdownx tabs.

The docs are also rendered by pluralintel.com, which reads this syntax::

    :::tabs
    :::tab First
    ...
    :::tab Second
    ...
    :::

mkdocstrings would otherwise read ``:::tabs`` as an API reference to a module
named ``tabs``, so each block is rewritten to ``=== "Title"`` before rendering.
"""

from __future__ import annotations

import re
from typing import Any

_FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
_TAB = re.compile(r"^:::tab\s+(.+?)\s*$")


def convert_tabs(markdown: str) -> str:
    """Rewrite ``:::tabs`` blocks outside code fences as pymdownx tabs.

    Returns:
        The page Markdown with every tab block rewritten.
    """
    out: list[str] = []
    fence: str | None = None
    in_tabs = False
    in_tab = False
    for line in markdown.split("\n"):
        stripped = line.strip()
        if fence is None and in_tabs:
            if stripped == ":::":
                in_tabs = in_tab = False
                out.append("")
                continue
            match = _TAB.match(stripped)
            if match:
                title = match.group(1).replace('"', '\\"')
                out.extend(["", f'=== "{title}"', ""])
                in_tab = True
                continue
        elif fence is None and stripped == ":::tabs":
            in_tabs = True
            continue
        fence_match = _FENCE.match(line)
        if fence_match:
            marker = fence_match.group(1)
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence):
                fence = None
        out.append(f"    {line}" if in_tab and line else line)
    return "\n".join(out)


def on_page_markdown(markdown: str, **kwargs: Any) -> str:
    """Rewrite each page's tab blocks before MkDocs renders it.

    Returns:
        The rewritten page Markdown.
    """
    return convert_tabs(markdown)
