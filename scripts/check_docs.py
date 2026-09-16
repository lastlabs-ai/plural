"""Validate documentation frontmatter, local links, and nav parity."""

from __future__ import annotations

import ast
import re
import shlex
from pathlib import Path

import yaml
from typer.main import get_command

from plural.cli.main import app

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
MKDOCS = ROOT / "mkdocs.yml"
LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
FRONTMATTER = re.compile(
    r"\A\ufeff?---[ \t]*\r?\n(?P<metadata>.*?)\r?\n---[ \t]*(?:\r?\n|$)",
    re.DOTALL,
)
HEADING = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
ANY_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE)
REQUIRED_FIELDS = frozenset({"route", "title", "order", "description", "audience", "nav"})
AUDIENCES = frozenset({"all", "developers", "operators", "maintainers", "internal"})
NAV_GROUPS = frozenset({"Start", "Build", "Run", "Interfaces", "Tutorials", "Operations"})
PACKAGE_NAV = [
    ("Start", "/docs", "index.md"),
    ("Start", "/docs/getting-started/concepts", "getting-started/concepts.md"),
    ("Start", "/docs/getting-started", "getting-started.md"),
    ("Build", "/docs/project/environments", "project/environments.md"),
    ("Build", "/docs/project/tasks", "project/tasks.md"),
    ("Build", "/docs/project/verifiers", "project/verifiers.md"),
    ("Build", "/docs/project/harnesses", "project/harnesses.md"),
    ("Build", "/docs/project/agents", "project/agents.md"),
    ("Build", "/docs/project/benchmarks", "project/benchmarks.md"),
    ("Run", "/docs/running/jobs", "running/jobs.md"),
    ("Run", "/docs/running/trials", "running/trials.md"),
    ("Run", "/docs/running/artifacts", "running/artifacts.md"),
    ("Run", "/docs/running/reviews", "running/reviews.md"),
    ("Run", "/docs/running/training", "running/training.md"),
    ("Interfaces", "/docs/sdk/evaluation", "sdk/evaluation.md"),
    ("Interfaces", "/docs/cli/evaluation", "cli/evaluation.md"),
    ("Interfaces", "/docs/interfaces/yaml", "interfaces/yaml.md"),
    ("Tutorials", "/docs/tutorials/support-queue", "tutorials/support-queue.md"),
    ("Tutorials", "/docs/tutorials/wordle", "tutorials/wordle.md"),
    ("Operations", "/docs/reference/integrations", "reference/integrations.md"),
]
FENCE = re.compile(r"^```(?P<language>[^\n]*)\n(?P<body>.*?)^```\s*$", re.MULTILINE | re.DOTALL)
INTERNAL_AUTHORING = re.compile(
    r"\b(?:[A-Za-z]+Definition|[A-Za-z]+Binding|schema_version|protocol|native_[a-z0-9_]*_v1)\b"
)


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


def _anchors(source: Path) -> set[str]:
    text = source.read_text(encoding="utf-8")
    output: set[str] = set()
    counts: dict[str, int] = {}
    for heading in ANY_HEADING.findall(text):
        plain = re.sub(r"<[^>]+>", "", heading)
        plain = re.sub(r"[^\w\s-]", "", plain.lower())
        base = re.sub(r"[-\s]+", "-", plain).strip("-")
        count = counts.get(base, 0)
        counts[base] = count + 1
        output.add(base if count == 0 else f"{base}_{count}")
    return output


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
            failures.append(f"{shown}: nav_group must be one of {', '.join(sorted(NAV_GROUPS))}")
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
            actual.add(
                (
                    str(meta.get("nav_group") or ""),
                    str(meta.get("route") or ""),
                    path.relative_to(DOCS),
                )
            )
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
    listed = _nav_paths(mkdocs_nav.get("nav"))
    expected_files = [relative for _, _, relative in PACKAGE_NAV]
    if listed != expected_files:
        failures.append(f"mkdocs.yml nav must match PACKAGE_NAV, got {listed}")


def _check_snippets(source: Path, text: str, failures: list[str]) -> None:
    shown = source.relative_to(ROOT)
    for index, match in enumerate(FENCE.finditer(text), start=1):
        language = match.group("language").strip().split(maxsplit=1)[0]
        body = match.group("body")
        if language == "python":
            try:
                ast.parse(body, filename=f"{shown} python fence {index}")
            except SyntaxError as exc:
                failures.append(f"{shown}: invalid Python fence {index} ({exc.msg})")
        if language == "yaml":
            try:
                yaml.safe_load(body)
            except yaml.YAMLError as exc:
                failures.append(f"{shown}: invalid YAML fence {index} ({exc})")
        if language in {"python", "yaml"}:
            internal = INTERNAL_AUTHORING.search(body)
            if internal:
                failures.append(
                    f"{shown}: internal authoring term {internal.group(0)!r} in fence {index}"
                )
        if language != "bash":
            continue
        for line in body.splitlines():
            stripped = line.strip()
            if not stripped.startswith("plural "):
                continue
            try:
                tokens = shlex.split(stripped.removesuffix("\\").strip())
            except ValueError:
                continue
            command = get_command(app)
            consumed = ["plural"]
            for token in tokens[1:]:
                commands = getattr(command, "commands", None)
                if not isinstance(commands, dict):
                    break
                if token not in commands:
                    failures.append(
                        f"{shown}: unknown CLI subcommand after {' '.join(consumed)!r} "
                        f"in {stripped!r}"
                    )
                    break
                command = commands[token]
                consumed.append(token)
            if len(consumed) == 1:
                failures.append(f"{shown}: unknown CLI command in {stripped!r}")


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
        if metadata.get("nav") is True:
            _check_snippets(source, text, failures)
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
            target, _, anchor = raw.partition("#")
            target = target.strip()
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            if not target:
                destination = source
            else:
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
            elif anchor and destination.suffix == ".md" and anchor not in _anchors(destination):
                failures.append(f"{source.relative_to(ROOT)} -> {raw} (missing anchor {anchor!r})")
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
