# Plural's sandbox base image: Debian slim with Python and what the engine needs to
# keep the App host apart from the Agent (sudo and useradd), plus curl, git, and the
# plural runtime's dependencies, so a Trial installs nothing from the network.
#
#   docker build --build-arg PYTHON_VERSION=3.12 -t plural-sandbox:py3.12 docker/sandbox

ARG PYTHON_VERSION=3.12
FROM python:${PYTHON_VERSION}-slim-bookworm

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
