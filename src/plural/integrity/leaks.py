"""Find what an Agent could read that gives the answer away.

The scan covers everything an Agent sees: the Task's instructions, ``info`` and
``metadata``, its files, the Environment's resources, and what the ``noop``
probe found in the sandbox's working folders. It flags:

- ``answer_key``: the Task's ``expected``, or a part of it at least six
  characters long, in something the Agent sees;
- ``git_history``: a git repository with more than its checked-out commit, or
  with tags or other branches, as in the SWE-bench leak;
- ``solution_file``: a file named like ``solution*``, ``answer*``,
  ``reference*``, ``*.orig``, or ``*.rej``;
- ``verifier_copy``: a file identical to a Verifier's source;
- ``canary``: the Benchmark's canary;
- ``not_scanned``: a file whose format can't be read, which is never reported
  as clean.

Text comes out of PDFs with ``pypdf`` when it is installed, and out of Word,
Excel, and PowerPoint files from their XML, with document properties,
comments, tracked changes, and hidden sheets included.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, Literal

from plural.common import FrozenModel

if TYPE_CHECKING:
    from plural.snapshots import SnapshotArchive

LeakKind = Literal[
    "answer_key", "git_history", "solution_file", "verifier_copy", "canary", "not_scanned"
]
LeakSeverity = Literal["critical", "warning", "info"]
MIN_ANSWER_LENGTH = 6
"""Shorter parts of an answer key are too common to mean anything."""
SUSPICIOUS_NAME = re.compile(r"^(solution|answer|reference)|\.(orig|rej)$", re.IGNORECASE)
COMMON_VALUES = frozenset(
    {"true", "false", "null", "none", "quote", "handoff", "yes", "no", "pass", "fail"}
)
_OFFICE = {".docx", ".docm", ".xlsx", ".xlsm", ".pptx", ".pptm"}
_UNREADABLE = {
    ".png": "an image",
    ".jpg": "an image",
    ".jpeg": "an image",
    ".gif": "an image",
    ".webp": "an image",
    ".bmp": "an image",
    ".tif": "an image",
    ".tiff": "an image",
    ".dwg": "a DWG drawing",
    ".doc": "a legacy Word file",
    ".xls": "a legacy Excel file",
    ".ppt": "a legacy PowerPoint file",
}
_TAG = re.compile(rb"<[^>]+>")
_SPACE = re.compile(r"\s+")


class LeakFinding(FrozenModel):
    """One way an Agent could read the answer.

    Attributes:
        kind: What leaked.
        path: Where, as the Agent sees it, such as ``resources/pricebook.md``.
        message: One line for a person.
        severity: ``critical`` gives the answer away; ``warning`` may;
            ``info`` could not be checked.
    """

    kind: LeakKind
    path: str
    message: str
    severity: LeakSeverity = "critical"


@dataclass(frozen=True)
class AgentFile:
    """One file an Agent can read, as it sees it.

    Attributes:
        path: The path the Agent sees.
        data: The file's bytes.
    """

    path: str
    data: bytes


def scan_task(
    *,
    instructions: str,
    expected: Any = None,
    info: Any = None,
    metadata: Mapping[str, Any] | None = None,
    files: Sequence[AgentFile] = (),
    verifier_sources: Mapping[str, bytes] | None = None,
    canary: str | None = None,
    workspace_scan: Mapping[str, Any] | None = None,
    vocabulary: str = "",
) -> tuple[LeakFinding, ...]:
    """Scan everything one Task shows an Agent.

    A part of ``expected`` that also appears in the instructions is the question,
    not the answer, so it is not flagged there or anywhere else. Nor is a part
    that appears in ``vocabulary``, the Environment's own source, which names
    things every Task shares, such as a catalog's product codes. The whole
    answer key is always looked for.

    Args:
        instructions: The Task's instructions.
        expected: The Task's answer key.
        info: The Task's ``info``, which the Agent sees.
        metadata: The Task's ``metadata``, which the Agent sees.
        files: The Task's files and the Environment's resources.
        verifier_sources: Each Verifier source file's bytes, by name.
        canary: The Benchmark's canary.
        workspace_scan: What the ``noop`` probe found in the sandbox.
        vocabulary: Text every Task in the Environment shares.

    Returns:
        Findings, most severe first.

    Examples:
        >>> found = scan_task(
        ...     instructions="Quote 20 tons of A36.",
        ...     expected={"total": "22800.00"},
        ...     files=[AgentFile("resources/notes.md", b"last total: 22800.00")],
        ... )
        >>> [(item.kind, item.path) for item in found]
        [('answer_key', 'resources/notes.md')]
    """
    findings: list[LeakFinding] = []
    needles = answer_needles(expected, f"{instructions}\n{vocabulary}")
    visible = [
        ("instructions", instructions),
        ("info", _json(info) if info is not None else ""),
        ("metadata", _json(metadata) if metadata else ""),
    ]
    for where, text in visible:
        findings.extend(
            _text_findings(
                where, text, needles, canary, expected=expected, skip_answer=where == "instructions"
            )
        )
    findings.extend(_file_findings(files, needles, canary, expected, verifier_sources))
    findings.extend(_workspace_findings(workspace_scan or {}))
    order = {"critical": 0, "warning": 1, "info": 2}
    return tuple(sorted(findings, key=lambda item: (order[item.severity], item.path, item.kind)))


def scan_files(
    files: Iterable[AgentFile],
    *,
    answers: Mapping[str, Any] | None = None,
    questions: Mapping[str, str] | None = None,
    canary: str | None = None,
    verifier_sources: Mapping[str, bytes] | None = None,
) -> tuple[LeakFinding, ...]:
    """Scan any set of files for the answer keys of many Tasks at once.

    This is how a folder or a snapshot that outlives one Task, such as an
    Agent's memory, is checked for held-out answers before it is used.

    Args:
        files: The files, as the Agent would see them.
        answers: Each Task's answer key, by Task name.
        questions: Each Task's instructions, by Task name. A part of a key
            that is also in the question is not flagged.
        canary: The Benchmark's canary.
        verifier_sources: Each Verifier source file's bytes, by name.

    Returns:
        Findings, most severe first. An answer key's finding names its Task.

    Examples:
        >>> found = scan_files(
        ...     [AgentFile("notes.md", b"quote-051 came to 22800.00")],
        ...     answers={"quote-051": {"total": "22800.00"}},
        ... )
        >>> [(item.kind, item.path) for item in found]
        [('answer_key', 'notes.md')]
        >>> found[0].message
        'The answer key "22800.00" of Task quote-051 appears in notes.md.'
    """
    files = list(files)
    findings = _file_findings(files, (), canary, None, verifier_sources)
    texts = [(item.path, extract_text(item.path, item.data)[0]) for item in files]
    for task, expected in sorted((answers or {}).items()):
        needles = answer_needles(expected, (questions or {}).get(task, ""))
        for path, content in texts:
            if content is None:
                continue
            for found in _text_findings(path, content, needles, None, expected=expected):
                message = found.message.replace("appears in", f"of Task {task} appears in", 1)
                findings.append(found.model_copy(update={"message": message}))
    order = {"critical": 0, "warning": 1, "info": 2}
    unique = dict.fromkeys(findings)
    return tuple(sorted(unique, key=lambda item: (order[item.severity], item.path, item.kind)))


def directory_files(root: Path) -> list[AgentFile]:
    """Every regular file under ``root``, by its path relative to it.

    A symbolic link is never followed, and a ``.git`` folder is left out.

    Returns:
        The files, sorted by path.
    """
    found = []
    for path in sorted(Path(root).rglob("*")):
        relative = path.relative_to(root)
        if ".git" in relative.parts or path.is_symlink() or not path.is_file():
            continue
        found.append(AgentFile(relative.as_posix(), path.read_bytes()))
    return found


def scan_directory(root: Path, **options: Any) -> tuple[LeakFinding, ...]:
    """:func:`scan_files` over every file in a folder.

    Returns:
        Findings, most severe first.
    """
    return scan_files(directory_files(root), **options)


def scan_snapshot(
    archive: SnapshotArchive, version: str, **options: Any
) -> tuple[LeakFinding, ...]:
    """:func:`scan_files` over one version of a snapshot, such as a workspace step.

    Returns:
        Findings, most severe first.
    """
    entries = archive.entries(version)
    return scan_files(
        [AgentFile(item.path, item.data) for item in entries if item.link is None], **options
    )


def _file_findings(
    files: Iterable[AgentFile],
    needles: Sequence[str],
    canary: str | None,
    expected: Any,
    verifier_sources: Mapping[str, bytes] | None,
) -> list[LeakFinding]:
    findings: list[LeakFinding] = []
    sources = {
        hashlib.sha256(data).hexdigest(): name for name, data in (verifier_sources or {}).items()
    }
    for item in files:
        name = PurePosixPath(item.path).name
        if SUSPICIOUS_NAME.search(name):
            findings.append(
                LeakFinding(
                    kind="solution_file",
                    path=item.path,
                    message=f"{item.path} is named like a solution; an Agent may read it as one.",
                    severity="warning",
                )
            )
        copied = sources.get(hashlib.sha256(item.data).hexdigest())
        if copied is not None:
            findings.append(
                LeakFinding(
                    kind="verifier_copy",
                    path=item.path,
                    message=f"{item.path} is a copy of the Verifier's {copied}.",
                )
            )
        content, reason = extract_text(item.path, item.data)
        if content is None:
            findings.append(
                LeakFinding(
                    kind="not_scanned",
                    path=item.path,
                    message=f"{item.path} was not scanned: {reason}.",
                    severity="info",
                )
            )
            continue
        findings.extend(_text_findings(item.path, content, needles, canary, expected=expected))
    return findings


def answer_needles(expected: Any, instructions: str = "") -> tuple[str, ...]:
    """The parts of an answer key worth looking for, normalized.

    The whole key as compact JSON, then each value at least
    :data:`MIN_ANSWER_LENGTH` characters long that is not a common word and
    does not appear in the instructions.

    Returns:
        Lowercased strings with whitespace collapsed.

    Examples:
        >>> answer_needles({"grade": "A572-50", "tons": 15, "price": 1140.0}, "A572-50 plate")
        ('{"grade":"a572-50","tons":15,"price":1140.0}', '1140.00')
    """
    if expected is None:
        return ()
    question = _normal(instructions)
    needles = []
    whole = _compact(expected)
    if len(whole) >= MIN_ANSWER_LENGTH and whole not in {"{}", "[]"}:
        needles.append(whole)
    for value in _leaves(expected):
        for text in _forms(value):
            normal = _normal(text)
            if (
                len(normal) >= MIN_ANSWER_LENGTH
                and normal not in COMMON_VALUES
                and normal not in question
                and normal not in needles
            ):
                needles.append(normal)
    return tuple(needles)


def extract_text(path: str, data: bytes) -> tuple[str | None, str]:
    r"""The text inside a file, for the scan.

    Returns:
        The text, or ``None`` and why it could not be read.

    Examples:
        >>> extract_text("notes.md", b"hello")
        ('hello', '')
        >>> extract_text("plan.png", b"\x89PNG")
        (None, 'an image, which has no text to scan')
    """
    suffix = PurePosixPath(path).suffix.lower()
    if suffix in _OFFICE:
        return _office(data)
    if suffix == ".pdf":
        return _pdf(data)
    if suffix in _UNREADABLE:
        return None, f"{_UNREADABLE[suffix]}, which has no text to scan"
    if suffix == ".zip":
        return _archive(data)
    try:
        return data.decode("utf-8"), ""
    except UnicodeDecodeError:
        try:
            return data.decode("latin-1") if _mostly_text(data) else None, "a binary format"
        except UnicodeDecodeError:
            return None, "a binary format"


def _text_findings(
    where: str,
    text: str,
    needles: Sequence[str],
    canary: str | None,
    *,
    expected: Any = None,
    skip_answer: bool = False,
) -> list[LeakFinding]:
    found = []
    if canary and canary in text:
        found.append(
            LeakFinding(
                kind="canary",
                path=where,
                message=f"The Benchmark's canary is in {where}; keep it out of what the "
                "Agent sees.",
            )
        )
    if skip_answer or not needles or not text:
        return found
    normal = _normal(text)
    squeezed = normal.replace(" ", "")
    for needle in needles:
        if needle in normal or (needle.startswith(("{", "[")) and needle in squeezed):
            shown = _display(needle, expected)
            shown = shown if len(shown) <= 60 else shown[:57] + "…"
            found.append(
                LeakFinding(
                    kind="answer_key",
                    path=where,
                    message=f'The answer key "{shown}" appears in {where}.',
                )
            )
            break
    return found


def _display(needle: str, expected: Any) -> str:
    whole = json.dumps(expected, separators=(",", ":"), default=str, ensure_ascii=False)
    if _normal(whole) == needle:
        return whole
    for value in _leaves(expected):
        for text in _forms(value):
            if _normal(text) == needle:
                return text
    return needle


def _workspace_findings(scan: Mapping[str, Any]) -> list[LeakFinding]:
    found = []
    for repository in scan.get("git") or ():
        if not isinstance(repository, Mapping):
            continue
        path = str(repository.get("path") or "?")
        commits = repository.get("commits")
        tags = list(repository.get("tags") or ())
        branches = [item for item in repository.get("branches") or () if "HEAD" not in str(item)]
        extra = []
        if isinstance(commits, int) and commits > 1:
            extra.append(f"{commits} commits")
        if tags:
            extra.append(f"{len(tags)} tag(s)")
        if len(branches) > 1:
            extra.append(f"{len(branches)} branches")
        if repository.get("error"):
            found.append(
                LeakFinding(
                    kind="not_scanned",
                    path=path,
                    message=f"git repository {path} was not scanned: {repository['error']}.",
                    severity="info",
                )
            )
        elif extra:
            found.append(
                LeakFinding(
                    kind="git_history",
                    path=path,
                    message=f"git repository {path} has history the Agent can read: "
                    f"{', '.join(extra)}. Ship one commit with no tags or other branches.",
                )
            )
    for path in scan.get("suspicious") or ():
        found.append(
            LeakFinding(
                kind="solution_file",
                path=str(path),
                message=f"{path} in the sandbox is named like a solution.",
                severity="warning",
            )
        )
    if scan.get("truncated"):
        found.append(
            LeakFinding(
                kind="not_scanned",
                path="workspace",
                message="The sandbox's working folders hold too many files to scan them all.",
                severity="info",
            )
        )
    return found


def _office(data: bytes) -> tuple[str | None, str]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return None, "an Office file that could not be opened"
    parts = []
    for name in archive.namelist():
        if name.endswith((".xml", ".rels")) and not name.startswith("[Content_Types]"):
            with archive.open(name) as member:
                parts.append(_TAG.sub(b" ", member.read(4_000_000)).decode("utf-8", "replace"))
    return " ".join(parts), ""


def _pdf(data: bytes) -> tuple[str | None, str]:
    try:
        from pypdf import PdfReader  # type: ignore[import-not-found]
    except ImportError:
        return None, "a PDF; install pypdf to scan PDFs"
    try:
        reader = PdfReader(io.BytesIO(data))
        parts = [page.extract_text() or "" for page in reader.pages]
        for page in reader.pages:
            for annotation in page.get("/Annots") or ():
                parts.append(str(annotation.get_object().get("/Contents") or ""))
        parts.extend(str(value) for value in (reader.metadata or {}).values())
    except Exception as exc:  # noqa: BLE001 - any parse failure means not scanned
        return None, f"a PDF that could not be read ({type(exc).__name__})"
    return "\n".join(parts), ""


def _archive(data: bytes) -> tuple[str | None, str]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return None, "a zip file that could not be opened"
    parts = []
    for name in archive.namelist():
        parts.append(name)
        with archive.open(name) as member:
            text, _ = extract_text(name, member.read(4_000_000))
        if text is None:
            return None, f"a zip file holding {name}, which can't be scanned"
        parts.append(text)
    return "\n".join(parts), ""


def _mostly_text(data: bytes) -> bool:
    sample = data[:4096]
    printable = sum(1 for byte in sample if 32 <= byte < 127 or byte in (9, 10, 13))
    return bool(sample) and printable / len(sample) > 0.95


def _leaves(value: Any) -> Iterable[Any]:
    if isinstance(value, Mapping):
        for item in value.values():
            yield from _leaves(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _leaves(item)
    elif value is not None and not isinstance(value, bool):
        yield value


def _forms(value: Any) -> tuple[str, ...]:
    if isinstance(value, float):
        return (f"{value:.2f}", f"{value:g}")
    return (str(value),)


def _compact(value: Any) -> str:
    return _normal(json.dumps(value, separators=(",", ":"), default=str, ensure_ascii=False))


def _json(value: Any) -> str:
    return json.dumps(value, default=str, ensure_ascii=False)


def _normal(text: str) -> str:
    return _SPACE.sub(" ", text.lower()).strip()


__all__ = [
    "COMMON_VALUES",
    "MIN_ANSWER_LENGTH",
    "AgentFile",
    "LeakFinding",
    "LeakKind",
    "LeakSeverity",
    "answer_needles",
    "directory_files",
    "extract_text",
    "scan_directory",
    "scan_files",
    "scan_snapshot",
    "scan_task",
]
