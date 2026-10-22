"""Content-addressed files that Tasks and Environments hand to an Agent.

A text file travels inline in its resource. Any other file, such as a PDF, a
Word document, a drawing, or an image, is a blob: the resource holds only its
``sha256:`` digest and content type, and the bytes live once in a local cache
and, after a push, in the hosted project.
"""

from __future__ import annotations

import hashlib
import mimetypes
import os
import re
import tempfile
from collections.abc import Mapping
from pathlib import Path

MAX_BLOB_BYTES = 16 * 1024 * 1024
MAX_TASK_FILE_BYTES = 256 * 1024 * 1024
MAX_INLINE_CHARACTERS = 1_048_576

BLOB_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")

# mimetypes leaves out the Office, CAD, and BIM formats Tasks commonly carry.
_CONTENT_TYPES = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".doc": "application/msword",
    ".xls": "application/vnd.ms-excel",
    ".ppt": "application/vnd.ms-powerpoint",
    ".dwg": "image/vnd.dwg",
    ".dxf": "image/vnd.dxf",
    ".ifc": "application/x-step",
    ".webp": "image/webp",
    ".heic": "image/heic",
    ".md": "text/markdown",
    ".yaml": "application/yaml",
    ".yml": "application/yaml",
    ".jsonl": "application/jsonl",
}

INLINE_IMAGE_TYPES = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})


def content_type_for(name: str, *, text: bool = False) -> str:
    """The MIME type a file's name implies.

    Args:
        name: The file name or path.
        text: Whether the file is UTF-8 text, which decides the fallback.

    Returns:
        The content type, ``text/plain`` or ``application/octet-stream`` when
        the name implies none.
    """
    suffix = Path(name).suffix.lower()
    known = _CONTENT_TYPES.get(suffix) or mimetypes.guess_type(name)[0]
    return known or ("text/plain" if text else "application/octet-stream")


def blob_digest(data: bytes) -> str:
    """The ``sha256:`` digest that names these bytes.

    Returns:
        The digest.
    """
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def check_digest(digest: str) -> str:
    """Refuse anything but a ``sha256:`` digest of 64 lowercase hex characters.

    Returns:
        The digest.

    Raises:
        ValueError: When the digest is malformed.
    """
    if not BLOB_DIGEST.fullmatch(digest):
        raise ValueError("A file digest must be sha256:<64 lowercase hex characters>")
    return digest


def blob_cache(environ: Mapping[str, str] | None = None) -> Path:
    """The folder that holds this machine's blobs, one file per digest.

    Returns:
        ``PLURAL_BLOB_CACHE``, else ``$XDG_CACHE_HOME/plural/blobs``, else
        ``~/.cache/plural/blobs``.
    """
    env = os.environ if environ is None else environ
    configured = env.get("PLURAL_BLOB_CACHE")
    if configured:
        return Path(configured).expanduser()
    xdg = env.get("XDG_CACHE_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".cache"
    return base / "plural" / "blobs"


def _location(digest: str, root: Path | None) -> Path:
    return (root or blob_cache()) / check_digest(digest).removeprefix("sha256:")


def store_blob(data: bytes, *, root: Path | None = None) -> str:
    """Keep bytes in the cache once, under their digest.

    Returns:
        The digest.

    Raises:
        ValueError: When the bytes exceed 16 MiB.
    """
    if len(data) > MAX_BLOB_BYTES:
        raise ValueError("A file may be at most 16 MiB")
    digest = blob_digest(data)
    target = _location(digest, root)
    if target.is_file():
        return digest
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=target.parent, prefix=".blob-")
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
        os.replace(temporary, target)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    return digest


def has_blob(digest: str, *, root: Path | None = None) -> bool:
    """Whether the cache holds a digest.

    Returns:
        ``True`` when the bytes are cached.
    """
    return _location(digest, root).is_file()


def read_blob(digest: str, *, root: Path | None = None) -> bytes:
    """The cached bytes of a digest, verified before they are returned.

    Returns:
        The bytes.

    Raises:
        FileNotFoundError: When the cache does not hold the digest.
        ValueError: When the cached bytes no longer match their digest.
    """
    location = _location(digest, root)
    if not location.is_file():
        raise FileNotFoundError(
            f"File {digest} is not on this machine. Run `plural pull` in the project, "
            "or push it from the machine that has it."
        )
    data = location.read_bytes()
    if blob_digest(data) != digest:
        location.unlink(missing_ok=True)
        raise ValueError(f"The cached copy of {digest} was corrupt and has been removed")
    return data


__all__ = [
    "INLINE_IMAGE_TYPES",
    "MAX_BLOB_BYTES",
    "MAX_INLINE_CHARACTERS",
    "MAX_TASK_FILE_BYTES",
    "blob_cache",
    "blob_digest",
    "check_digest",
    "content_type_for",
    "has_blob",
    "read_blob",
    "store_blob",
]
