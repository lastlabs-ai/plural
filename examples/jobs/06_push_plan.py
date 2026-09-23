"""Preview what ``plural benchmark push support-triage --with-deps`` would upload.

This runs offline against the first-project example. A real push uploads each
package privately, dependencies first, and reuses any revision whose content
already matches.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

from plural.harness.retrieval import archive_bytes, validate_archive
from plural.project import Project, ResourceRef, Workspace

sys.dont_write_bytecode = True
workspace = Workspace(Project.find(Path(__file__).resolve().parents[1] / "first-project"))
order = workspace.dependency_order([ResourceRef("benchmark", "support-triage")])
for ref in order:
    resource = workspace.load(ref)
    payload = archive_bytes(resource.directory)
    files = validate_archive(payload)  # the server's upload guardrails; raises on rejection
    digest = hashlib.sha256(payload).hexdigest()
    print(f"{ref!s:32} {resource.version:8} sha256:{digest[:12]}  {len(files)} files")

assert str(order[-1]) == "benchmark/support-triage"
print(f"{len(order)} revisions, dependencies first. Nothing is made public.")
