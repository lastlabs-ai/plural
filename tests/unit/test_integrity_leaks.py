"""The leak scan: what in a Task's files and sandbox gives the answer away."""

from __future__ import annotations

import io
import zipfile

from plural.integrity.leaks import AgentFile, answer_needles, extract_text, scan_task

KEY = {"decision": "quote", "grade": "A572-50", "total": "22800.00"}


def _kinds(found: tuple) -> list[tuple[str, str, str]]:
    return [(item.kind, item.path, item.severity) for item in found]


def _zip(name: str, text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(name, text)
    return buffer.getvalue()


def test_the_whole_key_and_its_long_parts_are_needles() -> None:
    needles = answer_needles(KEY, "Quote 75 tons of A572-50.")
    assert needles[0] == '{"decision":"quote","grade":"a572-50","total":"22800.00"}'
    assert "22800.00" in needles
    assert "a572-50" not in needles, "a part the instructions name is the question"
    assert "quote" not in needles, "too short to mean anything on its own"


def test_the_answer_in_a_text_file_is_critical() -> None:
    found = scan_task(
        instructions="Quote 75 tons of A572-50.",
        expected=KEY,
        files=[AgentFile("resources/log.md", b"Last total was 22,800.00, no: 22800.00")],
    )
    assert _kinds(found) == [("answer_key", "resources/log.md", "critical")]


def test_the_compact_key_is_found_even_when_reformatted() -> None:
    pretty = b'{\n  "decision": "quote",\n  "grade": "A572-50",\n  "total": "22800.00"\n}'
    found = scan_task(instructions="", expected=KEY, files=[AgentFile("old.json", pretty)])
    assert [item.kind for item in found] == ["answer_key"]
    assert '"grade":"A572-50"' in found[0].message, "shown as written, not lowercased"


def test_office_files_and_archives_are_read() -> None:
    document = _zip("word/document.xml", "<w:p><w:t>Total 22800.00</w:t></w:p>")
    archive = _zip("notes/old.txt", "22800.00")
    found = scan_task(
        instructions="",
        expected=KEY,
        files=[AgentFile("brief.docx", document), AgentFile("backup.zip", archive)],
    )
    assert sorted(item.path for item in found if item.kind == "answer_key") == [
        "backup.zip",
        "brief.docx",
    ]


def test_files_without_text_are_reported_not_scanned() -> None:
    assert extract_text("plan.png", b"\x89PNG\r\n")[0] is None
    found = scan_task(
        instructions="",
        expected=KEY,
        files=[AgentFile("plan.png", b"\x89PNG\r\n"), AgentFile("site.dwg", b"AC1032\x00\x01")],
    )
    assert {(item.kind, item.severity) for item in found} == {("not_scanned", "info")}


def test_vocabulary_shared_by_every_task_is_not_a_leak() -> None:
    found = scan_task(
        instructions="Quote 75 tons.",
        expected={"grade": "A572-50", "tons": 75},
        files=[AgentFile("environment/catalog.py", b'GRADES = ["A36", "A572-50"]')],
        vocabulary='GRADES = ["A36", "A572-50"]',
    )
    assert found == ()


def test_solution_names_verifier_copies_and_the_canary() -> None:
    verifier = b"def check(episode):\n    return 1.0\n"
    canary = "plural-canary-1234"
    found = scan_task(
        instructions="",
        info={"hint": f"see {canary}"},
        files=[AgentFile("solution.py", b"pass"), AgentFile("copy.py", verifier)],
        verifier_sources={"verify.py": verifier},
        canary=canary,
    )
    assert sorted((item.kind, item.severity) for item in found) == [
        ("canary", "critical"),
        ("solution_file", "warning"),
        ("verifier_copy", "critical"),
    ]


def test_git_history_in_the_sandbox_is_critical() -> None:
    found = scan_task(
        instructions="",
        workspace_scan={
            "git": [
                {"path": "/repo", "commits": 3, "tags": ["v1"], "branches": ["main"]},
                {"path": "/workspace", "commits": 1, "tags": [], "branches": ["main"]},
                {"path": "/src", "error": "dubious ownership"},
            ]
        },
    )
    assert _kinds(found) == [
        ("git_history", "/repo", "critical"),
        ("not_scanned", "/src", "info"),
    ]
    assert "3 commits, 1 tag(s)" in found[0].message
