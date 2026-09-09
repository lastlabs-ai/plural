"""Run package execution examples with every external integration disabled."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = tuple(sorted((ROOT / "examples" / "jobs").glob("[0-9][0-9]_*.py")))
LIVE_FLAGS = ("PLURAL_RUN_DOCKER", "PLURAL_RUN_DAYTONA", "PLURAL_RUN_STUDIO")


def main() -> int:
    """Execute each documented example in offline mode.

    Returns:
        Zero after every example succeeds.
    """
    environment = os.environ.copy()
    for name in LIVE_FLAGS:
        environment.pop(name, None)
    for path in EXAMPLES:
        print(f"==> {path.relative_to(ROOT)}")
        subprocess.run(
            [sys.executable, str(path)],
            cwd=ROOT,
            env=environment,
            check=True,
        )
    print(f"Offline package examples passed ({len(EXAMPLES)} files).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
