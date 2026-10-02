# syntax=docker/dockerfile:1
# peira reproducible environment.
#
# Single-stage build: the maturin PEP 517 backend compiles the optional
# PyO3 accelerator (peira._core) from crates/peira-python as part of
# `pip install -e .`, so no separate Rust build stage or manual .so
# copy is needed. The Rust toolchain is installed in the image because
# the PEP 517 build runs at install time.
#
# Build-only by default. No image is pushed to any registry. See
# .github/workflows/docker-build.yml and docs/Reproducibility.md.
#
#   docker build -t peira:local .
#   docker build -t peira:local --build-arg EXTRAS=all .
#   docker run --rm peira:local run --adapter mock --suite trial --seed 0 --out /tmp/runs

FROM python:3.12-slim-bookworm AS runtime

# Which extras to install. `dev` (the default) covers the base
# package plus the test tooling CI uses. `all` adds the Hugging Face
# and LLM-adapter extras. Large, pulls torch.
ARG EXTRAS=dev

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /peira

# Rust toolchain for maturin's PEP 517 build of peira._core. Pinned by
# rust-toolchain.toml (1.98.1); the minimal profile keeps the layer small.
# build-essential provides the C linker (cc) that rustc needs.
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates build-essential && \
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | \
      sh -s -- -y --profile minimal && \
    rm -rf /var/lib/apt/lists/*
ENV PATH="/root/.cargo/bin:${PATH}"

# Install the pinned third-party dependencies first. This layer only
# rebuilds when the lockfile changes, not on every code edit.
# uv.lock is the single source of truth. `uv export` projects it to a
# hash-pinned requirements file at build time. uv reads hashes from
# index metadata, so even the torch CUDA wheels get hash pins with no
# multi-gigabyte downloads. pip installs that file with
# --require-hashes, which makes the install tamper-evident. The uv
# binary is pinned to an exact release, like every other image pin in
# this file.
COPY --from=ghcr.io/astral-sh/uv:0.12.21 /uv /uvx /bin/
COPY pyproject.toml uv.lock ./
RUN if [ "$EXTRAS" = "all" ]; then \
      uv export --frozen --format requirements-txt --no-emit-project --all-extras -o /tmp/pinned.txt; \
    else \
      uv export --frozen --format requirements-txt --no-emit-project --extra dev -o /tmp/pinned.txt; \
    fi && \
    pip install --require-hashes -r /tmp/pinned.txt && \
    rm /tmp/pinned.txt

# Install peira itself, editable from the /peira checkout. The editable
# install is load-bearing, not a shortcut: cli.py and dataset.py resolve
# the repo root as three levels up from python/peira/cli.py, so the
# package must live in the checkout layout rather than site-packages.
# The base tier has zero third-party runtime dependencies by design (see
# AGENTS.md); --no-deps keeps it that way and lets the lockfile stay the
# single source of truth for everything else.
#
# maturin is the PEP 517 build backend, so this step compiles peira._core
# in place (needs the crates/ tree and the Cargo manifests, copied
# below). The extension suffix is computed by maturin, not hardcoded, so
# the Dockerfile survives Python upgrades.
COPY pyproject.toml README.md Cargo.toml Cargo.lock rust-toolchain.toml ./
COPY python/ python/
COPY crates/ crates/
RUN pip install -e . --no-deps && \
    python3 -c "from peira._rust import RUST_AVAILABLE; assert RUST_AVAILABLE, 'Rust extension failed to import'"

# Ship the versioned datasets so suite runs work out of the box.
# They are part of the repo snapshot; refresh by rebuilding.
COPY dataset/ dataset/

# The CLI writes run artifacts wherever --out points; default to a
# writable home for the non-root user.
RUN useradd --create-home --shell /bin/bash peira && \
    chown -R peira:peira /peira /home/peira
USER peira
WORKDIR /home/peira

ENTRYPOINT ["peira"]
CMD ["--help"]
