"""Check local Markdown links without fetching external resources."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")


def main() -> int:
    """Report unresolved local Markdown links.

    Returns:
        Zero when every local link resolves, otherwise one.
    """
    failures: list[str] = []
    for source in sorted(DOCS.rglob("*.md")):
        text = source.read_text(encoding="utf-8")
        for raw in LINK.findall(text):
            target = raw.split("#", 1)[0].strip()
            if not target or target.startswith(("http://", "https://", "mailto:")):
                continue
            destination = (source.parent / target).resolve()
            if target.endswith("/"):
                destination /= "index.md"
            if destination.is_dir():
                destination /= "index.md"
            if not destination.exists():
                shown = (
                    destination.relative_to(ROOT)
                    if destination.is_relative_to(ROOT)
                    else destination
                )
                failures.append(f"{source.relative_to(ROOT)} -> {target} ({shown})")
    if failures:
        print("Broken internal documentation links:")
        for failure in failures:
            print(f"  {failure}")
        return 1
    print("Internal documentation links are valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
