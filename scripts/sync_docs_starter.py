"""Keep the downloadable archive aligned with the starter.

Run after editing examples/first-project. Use --check to detect drift without writes.
"""

import io
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "examples/first-project"


def _write(path, content):
    if "--check" in sys.argv:
        if not path.exists() or path.read_bytes() != content:
            raise SystemExit(f"Starter documentation is stale: {path}")
    else:
        path.write_bytes(content)


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
print("Starter download matches the example.")
