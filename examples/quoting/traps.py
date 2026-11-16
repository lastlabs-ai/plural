"""Plant the quoting example's grader bug and integrity traps in a copy of it.

The example in this folder is the clean fixture. This script copies it and plants
whichever problems you name, so `plural eval check` and the Inspector have something
real to find:

    python traps.py /tmp/quoting-traps --all
    python traps.py /tmp/quoting-bug --enable unit-bug

- unit-bug: the answer keys of three requests in hundredweight (quote-016, quote-020,
  quote-053) record the cwt figure as short tons, so a correct quote fails.
- broken-check: quote-024 is graded by quote-check-legacy, which forgot the
  decision_correct gate, so an Agent that does nothing passes.
- leaked-key: the Environment ships a quote log holding quote-009's answer key.
- git-history: quote-013 runs in an image whose /repo has older commits and a tag,
  one of which held the answers. It needs Docker, and runs from the project folder.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
TRAPS = ("unit-bug", "broken-check", "leaked-key", "git-history")
UNIT_BUG = {"quote-016": (15, 300), "quote-020": (75, 1500), "quote-053": (20, 400)}
BROKEN_CHECK_TASK = "quote-024"
LEAKED_TASK = "quote-009"
GIT_TASK = "quote-013"
IGNORED = shutil.ignore_patterns(".plural", "__pycache__", ".venv", "*.pyc")

DOCKERFILE = """\
FROM python:3.12-slim
RUN apt-get update \\
 && apt-get install -y --no-install-recommends git sudo passwd \\
 && rm -rf /var/lib/apt/lists/*
WORKDIR /repo
RUN git init -q -b main \\
 && git config user.email desk@forge-steel.example \\
 && git config user.name "Quoting desk" \\
 && echo "# Forge Steel quoting tools" > README.md \\
 && git add . && git commit -qm "Start the quoting tools" \\
 && echo '{ANSWERS}' | base64 -d > answers.json \\
 && git add . && git commit -qm "Add answers for the eval" \\
 && git rm -q answers.json && git commit -qm "Remove answers" \\
 && git tag v1
"""


def plant(destination: Path, traps: set[str]) -> None:
    """Copy the clean example to ``destination`` and plant ``traps`` in it."""
    unknown = traps - set(TRAPS)
    if unknown:
        raise SystemExit(f"Unknown trap: {', '.join(sorted(unknown))}. Choose from {TRAPS}.")
    if destination.exists() and any(destination.iterdir()):
        raise SystemExit(f"{destination} is not empty.")
    shutil.copytree(HERE, destination, ignore=IGNORED, dirs_exist_ok=True)
    (destination / "traps.py").unlink()
    if "unit-bug" in traps:
        for task, (tons, cwt) in UNIT_BUG.items():
            _replace(
                destination / "tasks" / task / "task.yaml", f"tons: {tons}\n", f"tons: {cwt}\n"
            )
    if "broken-check" in traps:
        legacy = destination / "verifiers" / "quote-check-legacy"
        shutil.copytree(destination / "verifiers" / "quote-check", legacy, ignore=IGNORED)
        _replace(legacy / "verifier.yaml", "name: quote-check\n", "name: quote-check-legacy\n")
        _replace(
            legacy / "verify.py",
            'GATES = ("decision_correct", "price_correct", "delivery_feasible", "above_cost")',
            'GATES = ("price_correct", "delivery_feasible", "above_cost")',
        )
        _replace(
            destination / "tasks" / BROKEN_CHECK_TASK / "task.yaml",
            "  - quote-check\n",
            "  - quote-check-legacy\n",
        )
    if "leaked-key" in traps:
        environment = destination / "environments" / "quoting"
        log = [{"request": f"RFQ {LEAKED_TASK}", "answer": _expected(destination, LEAKED_TASK)}]
        (environment / "resources").mkdir(exist_ok=True)
        (environment / "resources" / "quote-log.json").write_text(
            json.dumps(log, indent=2) + "\n", encoding="utf-8"
        )
        with (environment / "environment.yaml").open("a", encoding="utf-8") as handle:
            handle.write("\nresources:\n  - resources/quote-log.json\n")
    if "git-history" in traps:
        source = destination / "environments" / "quoting"
        target = destination / "environments" / "quoting-git"
        shutil.copytree(source, target, ignore=IGNORED)
        answers = json.dumps({GIT_TASK: _expected(destination, GIT_TASK)})
        answers = base64.b64encode(answers.encode()).decode()
        (target / "Dockerfile").write_text(DOCKERFILE.replace("{ANSWERS}", answers), "utf-8")
        manifest = (target / "environment.yaml").read_text(encoding="utf-8")
        manifest = manifest.replace("name: quoting\n", "name: quoting-git\n", 1)
        manifest = re.sub(
            r"runtime:\n  provider: local\n",
            "runtime:\n  provider: docker\n"
            "  build_context: environments/quoting-git\n"
            "  dockerfile: environments/quoting-git/Dockerfile\n",
            manifest,
        )
        (target / "environment.yaml").write_text(manifest, encoding="utf-8")
        _replace(
            destination / "tasks" / GIT_TASK / "task.yaml",
            "environment: quoting\n",
            "environment: quoting-git\n",
        )
    for stale in ("plural.lock",):
        (destination / stale).unlink(missing_ok=True)


def _expected(root: Path, task: str) -> dict[str, object]:
    import yaml

    payload = yaml.safe_load((root / "tasks" / task / "task.yaml").read_text(encoding="utf-8"))
    return dict(payload["expected"])


def _replace(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"{path}: expected to find {old!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    """Parse the command line and plant the traps."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("destination", type=Path, help="An empty or new folder for the copy.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--enable", help=f"Comma-separated traps: {', '.join(TRAPS)}.")
    group.add_argument("--all", action="store_true", help="Plant every trap.")
    arguments = parser.parse_args()
    traps = set(TRAPS) if arguments.all else {item.strip() for item in arguments.enable.split(",")}
    plant(arguments.destination, traps)
    print(f"Planted {', '.join(sorted(traps))} in {arguments.destination}.")
    print(f"Next: cd {arguments.destination} && plural eval check")


if __name__ == "__main__":
    main()
