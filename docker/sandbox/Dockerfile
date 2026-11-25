# Plural's sandbox base image: Debian slim with Python and what the engine needs to
# keep the App host apart from the Agent (sudo and useradd), plus curl, git, and the
# plural runtime's dependencies, so a Trial installs nothing from the network.
#
#   docker build --build-arg PYTHON_VERSION=3.12 -t plural-sandbox:py3.12 docker/sandbox
#
# The vendor target adds Node.js and the pinned Claude Code and Codex CLIs, so the
# built-in vendor Harnesses run on a gateway-only network:
#
#   docker build --target vendor -t plural-sandbox:py3.12-vendor docker/sandbox

ARG PYTHON_VERSION=3.12
FROM python:${PYTHON_VERSION}-slim-bookworm AS base

ARG PLURAL_VERSION=""

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl git sudo passwd procps \
 && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --no-cache-dir --upgrade pip \
 && if [ -n "$PLURAL_VERSION" ]; then \
      python -m pip install --no-cache-dir "plural==${PLURAL_VERSION}"; \
    else \
      python -m pip install --no-cache-dir \
        "httpx>=0.27,<1" "pydantic>=2.7,<3" "PyYAML>=6.0,<7" "typer>=0.12,<1"; \
    fi

# The engine runs as root to create the App host's and the Agent's users; the Agent's
# user is never in sudoers, so it cannot escalate.
WORKDIR /workspace
LABEL org.opencontainers.image.source="https://github.com/lastlabs-ai/plural" \
      org.opencontainers.image.description="Plural sandbox base image" \
      org.opencontainers.image.licenses="Apache-2.0"

FROM base AS vendor

# The versions the SDK pins (BUILTIN_HARNESSES in plural.harness.builtins);
# tests/unit/test_sandbox_image.py fails when they drift.
ARG NODE_MAJOR=22
ARG CLAUDE_CODE_VERSION=2.1.236
ARG CODEX_VERSION=0.153.2

RUN curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" | bash - \
 && apt-get install -y --no-install-recommends nodejs \
 && rm -rf /var/lib/apt/lists/* \
 && npm install --global --no-fund --no-audit \
      "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" \
      "@openai/codex@${CODEX_VERSION}" \
 && npm cache clean --force \
 && claude --version && codex --version

LABEL org.opencontainers.image.description="Plural sandbox image with Node.js and the pinned Claude Code and Codex CLIs"

FROM base
