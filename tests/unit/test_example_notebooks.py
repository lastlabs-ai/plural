from __future__ import annotations

import json
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_NOTEBOOKS = [
    _ROOT / "examples" / "environment" / name / "walkthrough.ipynb"
    for name in ("wordle", "library", "twitter")
]


@pytest.mark.parametrize("notebook_path", _NOTEBOOKS, ids=lambda path: path.parent.name)
def test_environment_walkthrough_notebook_executes(
    notebook_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Run code cells in order without requiring Jupyter in the test suite."""
    notebook = json.loads(notebook_path.read_text(encoding="utf-8"))
    namespace = {"__name__": "__notebook__"}
    monkeypatch.syspath_prepend(str(_ROOT))
    monkeypatch.chdir(tmp_path)

    for index, cell in enumerate(notebook["cells"]):
        if cell["cell_type"] != "code":
            continue
        source = "".join(cell["source"])
        exec(compile(source, f"{notebook_path.name}:cell-{index}", "exec"), namespace)
