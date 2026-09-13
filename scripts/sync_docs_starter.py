"""Keep the complete tutorial and downloadable archive aligned with the starter.

Run after editing examples/first-project. Use --check to detect drift without writes.
"""

import io
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "examples/first-project"
FILES = ["environment/world.py", "environment/commands.py", "verifiers/correct.py", "build.py"]


def _write(path, content):
    if "--check" in sys.argv:
        if not path.exists() or path.read_bytes() != content:
            raise SystemExit(f"Starter documentation is stale: {path}")
    else:
        path.write_bytes(content)


tutorial = ROOT / "docs/tutorials/first-project.md"
blocks = iter((SOURCE / name).read_text().rstrip() for name in FILES)
text, count = re.subn(
    r"```python\n.*?```",
    lambda _: "```python\n" + next(blocks) + "\n```",
    tutorial.read_text(),
    flags=re.S,
)
if count != len(FILES):
    raise SystemExit("Expected exactly four complete Python files in the tutorial")
_write(tutorial, text.encode())
archive = io.BytesIO()
with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
    for path in sorted(SOURCE.rglob("*")):
        if not path.is_file() or {"__pycache__", ".plural"} & set(path.parts):
            continue
        if path.name in {"state.json", "observation.json"}:
            continue
        entry = zipfile.ZipInfo("first-project/" + path.relative_to(SOURCE).as_posix())
        entry.compress_type = zipfile.ZIP_DEFLATED
        bundle.writestr(entry, path.read_bytes())
_write(ROOT / "docs/assets/first-project.zip", archive.getvalue())
print("Starter walkthrough and download match the example.")
