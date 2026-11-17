#!/usr/bin/env bash
# The Harness smoke test, as one command for a nightly schedule: the native loop, Claude
# Code, Codex and Hermes each run a Task only a file write can pass, through the real
# gateway, and fail if any model call goes around it.
#
# Needs PLURAL_API_KEY, PLURAL_SMOKE_PROJECT (the hosted project the key records into),
# and Node.js 22 or newer on PATH for Claude Code and Codex. PLURAL_API_URL and
# PLURAL_GATEWAY_URL pick another deployment. Exits non-zero when any Harness fails.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${PLURAL_API_KEY:?set PLURAL_API_KEY}"
: "${PLURAL_SMOKE_PROJECT:?set PLURAL_SMOKE_PROJECT to the hosted project to record into}"
node -e 'process.exit(Number(process.versions.node.split(".")[0]) >= 22 ? 0 : 1)' \
  || { echo "Node.js 22 or newer must be on PATH for Claude Code and Codex" >&2; exit 1; }
PLURAL_RUN_HARNESS_SMOKE=1 exec uv run pytest -p no:cacheprovider tests/live/test_harness_smoke.py -v "$@"
