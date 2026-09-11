"""Validate documentation frontmatter, local links, and nav parity."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
MKDOCS = ROOT / "mkdocs.yml"
LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
FRONTMATTER = re.compile(
    r"\A\ufeff?---[ \t]*\r?\n(?P<metadata>.*?)\r?\n---[ \t]*(?:\r?\n|$)",
    re.DOTALL,
)
HEADING = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
REQUIRED_FIELDS = frozenset({"route", "title", "order", "description", "audience", "nav"})
AUDIENCES = frozenset({"all", "developers", "operators", "maintainers", "internal"})
NAV_GROUPS = frozenset({"Start", "Project", "Running", "Tutorial", "Reference"})
PACKAGE_NAV = [
    ("Start", "/docs", "index.md"),
    ("Start", "/docs/motivation", "motivation.md"),
    ("Start", "/docs/getting-started", "getting-started.md"),
    ("Project", "/docs/project/environments", "project/environments.md"),
    ("Project", "/docs/project/tasks", "project/tasks.md"),
    ("Project", "/docs/project/verifiers", "project/verifiers.md"),
    ("Project", "/docs/project/agents", "project/agents.md"),
    ("Project", "/docs/project/benchmarks", "project/benchmarks.md"),
    ("Running", "/docs/running/jobs", "running/jobs.md"),
    ("Running", "/docs/running/traces", "running/traces.md"),
    ("Running", "/docs/running/reviews", "running/reviews.md"),
    ("Tutorial", "/docs/tutorials/wordle", "tutorials/wordle.md"),
    ("Reference", "/docs/reference/definitions", "reference/definitions.md"),
    ("Reference", "/docs/reference/cli-commands", "reference/cli-commands.md"),
    ("Reference", "/docs/reference/glossary", "reference/glossary.md"),
    ("Reference", "/docs/reference/integrations", "reference/integrations.md"),
]


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
    nav = metadata["nav"]
    if not isinstance(nav, bool):
        failures.append(f"{shown}: nav must be a boolean")
    elif nav:
        group = metadata.get("nav_group")
        if not isinstance(group, str) or group not in NAV_GROUPS:
            failures.append(
                f"{shown}: nav_group must be one of {', '.join(sorted(NAV_GROUPS))}"
            )
    return metadata


def _nav_paths(node: object) -> list[str]:
    paths: list[str] = []
    if isinstance(node, str):
        paths.append(node)
    elif isinstance(node, dict):
        for value in node.values():
            paths.extend(_nav_paths(value))
    elif isinstance(node, list):
        for item in node:
            paths.extend(_nav_paths(item))
    return paths


def _nav_parity(documents: dict[str, dict[str, object]], failures: list[str]) -> None:
    expected = {(group, route, Path(relative)) for group, route, relative in PACKAGE_NAV}
    actual = set()
    for path, meta in documents.items():
        if meta.get("nav") is True:
            actual.add((str(meta.get("nav_group") or ""), str(meta.get("route") or ""), path.relative_to(DOCS)))
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        if missing:
            failures.append(f"nav missing: {missing}")
        if extra:
            failures.append(f"nav extra: {extra}")

    mkdocs_text = MKDOCS.read_text(encoding="utf-8")
    nav_block = mkdocs_text.split("\nnav:\n", 1)[1]
    mkdocs_nav = yaml.safe_load("nav:\n" + nav_block)
    listed = [item for item in _nav_paths(mkdocs_nav.get("nav")) if item != "reference/api.md"]
    expected_files = [relative for _, _, relative in PACKAGE_NAV]
    if listed != expected_files:
        failures.append(f"mkdocs.yml nav must match PACKAGE_NAV, got {listed}")


def main() -> int:
    """Report invalid metadata and unresolved local Markdown links.

    Returns:
        Zero when every local link resolves, otherwise one.
    """
    failures: list[str] = []
    routes: dict[str, Path] = {}
    orders: dict[int, Path] = {}
    documents: dict[Path, dict[str, object]] = {}
    for source in sorted(DOCS.rglob("*.md")):
        text = source.read_text(encoding="utf-8")
        metadata = _metadata(source, text, failures)
        documents[source] = metadata
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
    _nav_parity(documents, failures)
    if failures:
        print("Documentation validation failures:")
        for failure in failures:
            print(f"  {failure}")
        return 1
    print(f"Documentation metadata and internal links are valid ({len(routes)} routes).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
