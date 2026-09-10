"""Validate documentation frontmatter and local links."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
FRONTMATTER = re.compile(r"\A---\n(?P<metadata>.*?)\n---\n", re.DOTALL)
HEADING = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
REQUIRED_FIELDS = frozenset({"route", "title", "order", "description", "audience"})
AUDIENCES = frozenset({"all", "developers", "operators", "maintainers", "internal"})


def intended_route(source: Path) -> str:
    """Return the stable pluralintel route derived from a docs path.

    Returns:
        A route rooted at ``/docs``.
    """
    relative = source.relative_to(DOCS).with_suffix("")
    parts = list(relative.parts)
    if parts and parts[-1] == "index":
        parts.pop()
    return "/docs" + (f"/{'/'.join(parts)}" if parts else "")


def _metadata(source: Path, text: str, failures: list[str]) -> dict[str, object]:
    match = FRONTMATTER.match(text)
    shown = source.relative_to(ROOT)
    if match is None:
        failures.append(f"{shown}: missing YAML frontmatter")
        return {}
    try:
        value = yaml.safe_load(match.group("metadata"))
    except yaml.YAMLError as exc:
        failures.append(f"{shown}: invalid YAML frontmatter ({exc})")
        return {}
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        failures.append(f"{shown}: frontmatter must be a string-keyed mapping")
        return {}
    metadata = dict(value)
    missing = sorted(REQUIRED_FIELDS - metadata.keys())
    if missing:
        failures.append(f"{shown}: missing frontmatter fields: {', '.join(missing)}")
        return metadata

    route = metadata["route"]
    expected_route = intended_route(source)
    if not isinstance(route, str) or route != expected_route:
        failures.append(f"{shown}: route must be {expected_route!r}, got {route!r}")
    title = metadata["title"]
    heading = HEADING.search(text[match.end() :])
    expected_title = heading.group(1).strip() if heading else None
    if not isinstance(title, str) or not title.strip():
        failures.append(f"{shown}: title must be a non-empty string")
    elif title.strip() != expected_title:
        failures.append(f"{shown}: title must match the H1 {expected_title!r}, got {title!r}")
    order = metadata["order"]
    if isinstance(order, bool) or not isinstance(order, int) or order < 0:
        failures.append(f"{shown}: order must be a non-negative integer")
    description = metadata["description"]
    if (
        not isinstance(description, str)
        or len(description.strip()) < 20
        or len(description.strip()) > 300
    ):
        failures.append(f"{shown}: description must contain 20-300 characters")
    audience = metadata["audience"]
    if not isinstance(audience, str) or audience not in AUDIENCES:
        failures.append(f"{shown}: audience must be one of {', '.join(sorted(AUDIENCES))}")
    return metadata


def main() -> int:
    """Report invalid metadata and unresolved local Markdown links.

    Returns:
        Zero when every local link resolves, otherwise one.
    """
    failures: list[str] = []
    routes: dict[str, Path] = {}
    orders: dict[int, Path] = {}
    for source in sorted(DOCS.rglob("*.md")):
        text = source.read_text(encoding="utf-8")
        metadata = _metadata(source, text, failures)
        route = metadata.get("route")
        if isinstance(route, str):
            previous = routes.setdefault(route, source)
            if previous != source:
                failures.append(
                    f"{source.relative_to(ROOT)}: route {route!r} duplicates "
                    f"{previous.relative_to(ROOT)}"
                )
        order = metadata.get("order")
        if isinstance(order, int) and not isinstance(order, bool):
            previous = orders.setdefault(order, source)
            if previous != source:
                failures.append(
                    f"{source.relative_to(ROOT)}: order {order} duplicates "
                    f"{previous.relative_to(ROOT)}"
                )
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
        print("Documentation validation failures:")
        for failure in failures:
            print(f"  {failure}")
        return 1
    print(f"Documentation metadata and internal links are valid ({len(routes)} routes).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
